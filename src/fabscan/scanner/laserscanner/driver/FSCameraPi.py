__author__ = "Mario Lukas"
__copyright__ = "Copyright 2017"
__license__ = "GPL v2"
__maintainer__ = "Mario Lukas"
__email__ = "info@mariolukas.de"

import cv2
import logging
import threading
import time

from fabscan.lib.util.FSInject import inject, singleton
from fabscan.FSConfig import ConfigInterface
from fabscan.FSSettings import SettingsInterface
import picamera
from picamera.exc import PiCameraError
from picamera.array import PiRGBArray

# Pi 3 + full-res BGR needs conservative MMAL buffer pressure to start reliably.
_DEFAULT_FRAMERATE = 15
# Applying ISP settings every frame adds MMAL pressure; throttle UI-driven tweaks.
_SETTINGS_UPDATE_INTERVAL_FRAMES = 15


class PiVideoStream:
    def __init__(self, config, settings, framerate, **kwargs):
        self._logger = logging.getLogger(__name__)
        self.config = config
        self.settings = settings
        self.framerate = framerate
        self.camera_kwargs = kwargs

        self.preview_resolution = (
            config.file.camera.preview_resolution.width,
            config.file.camera.preview_resolution.height,
        )
        self.requested_resolution = (
            config.file.camera.resolution.width,
            config.file.camera.resolution.height,
        )

        self.camera = None
        self.rawCapture = None
        self.stream = None

        self.high_res_frame = None
        self.low_res_frame = None
        self.stopped = False
        self._frame_seq = 0

        self._init_camera_and_pipeline(initial_startup=True)

    def _init_camera_and_pipeline(self, initial_startup=False):
        """
        Open PiCamera and start capture_continuous using the *effective* resolution
        Picamera selects (OV5647 rounds modes). PiRGBArray must match that size or
        MMAL teardown can raise Incorrect buffer length after timeouts.
        """
        if self.camera is not None:
            self._release_pipeline(hard=True)

        try:
            self._logger.info(
                "Opening PiCamera at %sx%s @ %sfps",
                self.requested_resolution[0],
                self.requested_resolution[1],
                self.framerate,
            )
            self.camera = picamera.PiCamera()
            if initial_startup:
                time.sleep(2)
                self.camera.awb_mode = 'fluorescent'
                time.sleep(1)
            else:
                time.sleep(0.3)
                self.camera.awb_mode = 'fluorescent'
                time.sleep(0.3)

            self.camera.resolution = self.requested_resolution
            w, h = self.camera.resolution
            eff_w, eff_h = int(w), int(h)
            if eff_w != self.requested_resolution[0] or eff_h != self.requested_resolution[1]:
                self._logger.info(
                    "PiCamera effective resolution %sx%s (requested %sx%s); "
                    "align config.camera.resolution with this to avoid calibration/size drift.",
                    eff_w,
                    eff_h,
                    self.requested_resolution[0],
                    self.requested_resolution[1],
                )

            self.camera.framerate = self.framerate
            for arg, value in self.camera_kwargs.items():
                setattr(self.camera, arg, value)

            self.rawCapture = PiRGBArray(self.camera, size=(eff_w, eff_h))
            self.stream = self.camera.capture_continuous(
                self.rawCapture, format="bgr", use_video_port=True
            )
        except Exception as e:
            self._release_pipeline(hard=True)
            self._logger.error(
                "PiCamera startup failed. Check camera cable, legacy camera support, "
                "GPU memory, and whether another process owns the camera: %s",
                e,
            )
            raise

    def _release_pipeline(self, hard=False):
        try:
            if self.stream is not None:
                self.stream.close()
        except Exception:
            pass
        self.stream = None

        try:
            if self.rawCapture is not None:
                self.rawCapture.close()
        except Exception:
            pass
        self.rawCapture = None

        if hard:
            try:
                if self.camera is not None:
                    self.camera.close()
            except Exception:
                pass
            self.camera = None

    def start_stream(self):
        t = threading.Thread(target=self.update, name=__name__ + '-Thread', args=())
        t.daemon = True
        t.start()
        return self

    def update(self):
        consecutive_errors = 0
        while not self.stopped:
            try:
                for fr in self.stream:
                    if self.stopped:
                        self._release_pipeline(hard=True)
                        return

                    self._frame_seq += 1
                    if self._frame_seq % _SETTINGS_UPDATE_INTERVAL_FRAMES == 0:
                        self.camera.contrast = self.settings.file.camera.contrast
                        self.camera.brightness = self.settings.file.camera.brightness
                        self.camera.saturation = self.settings.file.camera.saturation

                    self.high_res_frame = fr.array
                    self.low_res_frame = cv2.resize(
                        self.high_res_frame, self.preview_resolution
                    )
                    self.rawCapture.truncate(0)
                    consecutive_errors = 0

            except PiCameraError as e:
                if self.stopped:
                    break
                consecutive_errors += 1
                self._logger.warning(
                    "PiCamera capture error #%s (%s): %s",
                    consecutive_errors,
                    type(e).__name__,
                    e,
                )
                self._release_pipeline(hard=True)
                if self.stopped:
                    break
                backoff = min(30.0, float(2 ** min(consecutive_errors, 4)))
                time.sleep(backoff)
                try:
                    self._init_camera_and_pipeline(initial_startup=False)
                except Exception as e2:
                    self._logger.error("PiCamera re-init failed: %s", e2)
                    time.sleep(5.0)

            except Exception as e:
                if self.stopped:
                    break
                consecutive_errors += 1
                self._logger.warning(
                    "Unexpected camera thread error #%s (%s): %s",
                    consecutive_errors,
                    type(e).__name__,
                    e,
                )
                self._release_pipeline(hard=True)
                if self.stopped:
                    break
                time.sleep(min(30.0, float(2 ** min(consecutive_errors, 4))))
                try:
                    self._init_camera_and_pipeline(initial_startup=False)
                except Exception as e2:
                    self._logger.error("Camera re-init failed: %s", e2)
                    time.sleep(5.0)

        self._release_pipeline(hard=True)

    def get_frame(self, preview=False):
        if preview:
            return self.low_res_frame
        else:
            return self.high_res_frame

    def stop_stream(self):
        self.stopped = True
        self._release_pipeline(hard=True)


@singleton(
    config=ConfigInterface,
    settings=SettingsInterface
)
class FSCameraPi:

    def __init__(self, config, settings):

        self._logger = logging.getLogger(__name__)
        self.config = config
        self.settings = settings
        self.stream = PiVideoStream(
            config=self.config,
            settings=self.settings,
            framerate=_DEFAULT_FRAMERATE,
        )

    def get_frame(self, preview=False):
        return self.stream.get_frame(preview=preview)

    def start_stream(self):
        return self.stream.start_stream()

    def stop_stream(self):
        self.stream.stop_stream()

    def is_idle(self):
        pass

    def flush_stream(self):
        pass
