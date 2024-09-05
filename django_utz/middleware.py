import threading
import logging

logger = logging.getLogger(__name__)

class DjangoUTZMiddleware:
    _local_thread_storage = threading.local()

    def __init__(self, get_response):
        self.get_response = get_response

    def process_request(self, request):
        logger.info("Processing request in DjangoUTZMiddleware")
        setattr(self._local_thread_storage, 'request_user_key', None)

    def process_response(self, request, response):
        logger.info("Processing response in DjangoUTZMiddleware")
        request_user_key = getattr(self._local_thread_storage, 'request_user_key', None)
        return response

    def __call__(self, request):
        logger.info("Calling DjangoUTZMiddleware")
        self.process_request(request)
        response = self.get_response(request)
        return self.process_response(request, response)
