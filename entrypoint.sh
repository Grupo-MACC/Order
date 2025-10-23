#!/bin/bash

echo "Service: ${SERVICE_NAME}"
IP=$(hostname -i)
export IP
echo "IP: ${IP}"

terminate() {
  echo "Termination signal received, shutting down..."
  kill -SIGTERM "$UVICORN_PID"
  wait "$UVICORN_PID"
  echo "Uvicorn has been terminated"
}

trap terminate SIGTERM SIGINT

uvicorn app_order.main:app \
  --host 0.0.0.0 \
  --port 5000 \
  --ssl-keyfile /certs/order/order-key.pem \
  --ssl-certfile /certs/order/order-cert.pem \
  --ssl-ca-certs /certs/ca.pem \
  --ssl-cert-reqs 2 &  # 2 = ssl.CERT_REQUIRED (cliente debe autenticarse)

UVICORN_PID=$!

wait "$UVICORN_PID"
