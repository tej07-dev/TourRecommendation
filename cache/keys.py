import hashlib
import json


class CacheKeys:

    @staticmethod
    def candidates(user_id: int):
        return f"rec:candidates:user:{user_id}"

    @staticmethod
    def recommendations(user_id: int, params: dict):
        hash_key = hashlib.md5(
            json.dumps(params, sort_keys=True).encode()
        ).hexdigest()

        return f"rec:ranked:user:{user_id}:{hash_key}"

    @staticmethod
    def user_embedding(user_id: int):
        return f"model:embedding:user:{user_id}"

    @staticmethod
    def place_embedding(place_id: int):
        return f"model:embedding:place:{place_id}"

    @staticmethod
    def weather(place_id: int):
        return f"external:weather:{place_id}"

    @staticmethod
    def youtube(place_id: int):
        return f"external:youtube:{place_id}"

    @staticmethod
    def route(hash_key: str):
        return f"external:route:{hash_key}"

    @staticmethod
    def model_version(model_name: str):
        return f"model:version:{model_name}"
