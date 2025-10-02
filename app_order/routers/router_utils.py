# -*- coding: utf-8 -*-
"""Util/Helper functions for router definitions."""
import logging
from fastapi import HTTPException
import requests

MACHINE_SERVICE_URL = "http://machine:5001"
DELIVERY_SERVICE_URL = "http://delivery:5002"

logger = logging.getLogger(__name__)


def raise_and_log_error(my_logger, status_code: int, message: str):
    """Raises HTTPException and logs an error."""
    my_logger.error(message)
    raise HTTPException(status_code, message)