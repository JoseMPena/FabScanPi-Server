def stop_thread_service(service, logger, name, timeout):
    if service is None:
        return True

    service.kill()
    logger.debug("Waiting for {0} exit...".format(name))

    if hasattr(service, "join"):
        service.join(timeout=timeout)

    if hasattr(service, "is_alive") and service.is_alive():
        logger.warning("{0} thread did not finish within {1}s".format(name, timeout))
        return False

    return True
