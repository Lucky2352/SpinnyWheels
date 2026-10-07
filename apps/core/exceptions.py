import logging

from django.db import DatabaseError
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler

logger = logging.getLogger("autoflow.api")


class DomainError(Exception):
    default_message = "The request could not be processed."
    status_code = status.HTTP_400_BAD_REQUEST

    def __init__(self, message=None):
        self.message = message or self.default_message
        super().__init__(self.message)


class ResourceNotFoundError(DomainError):
    default_message = "The requested resource does not exist."
    status_code = status.HTTP_404_NOT_FOUND


class ConflictError(DomainError):
    default_message = "The request conflicts with the current state of the resource."
    status_code = status.HTTP_409_CONFLICT


class PermissionDeniedError(DomainError):
    default_message = "You do not have permission to perform this action."
    status_code = status.HTTP_403_FORBIDDEN


class InvalidStateError(DomainError):
    default_message = "The operation is not allowed in the current state."
    status_code = status.HTTP_409_CONFLICT


def domain_exception_handler(exc, context):
    if isinstance(exc, DomainError):
        return Response({"detail": exc.message}, status=exc.status_code)

    if isinstance(exc, DatabaseError):
        logger.exception("Database failure while handling an API request")
        return Response(
            {"detail": "A database error occurred while processing the request."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    return exception_handler(exc, context)
