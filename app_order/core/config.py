import os

class Settings():
    ALGORITHM: str = "RS256"
    RABBITMQ_HOST = "amqp://guest:guest@rabbitmq/"
    EXCHANGE_NAME = "broker"
    
    class Config:
        env_file= ".env"
        env_file_encoding = "utf-8"

settings = Settings()