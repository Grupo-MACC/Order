import os

class Settings():
    ALGORITHM: str = "RS256"
    
    class Config:
        env_file= ".env"
        env_file_encoding = "utf-8"

settings = Settings()