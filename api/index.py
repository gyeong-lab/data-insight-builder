import os
import sys

# Vercel Serverless 실행 환경에서 프로젝트 루트 경로를 sys.path에 등록
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app as flask_app
import logging
from urllib.parse import parse_qs, urlencode

logger = logging.getLogger(__name__)

class VercelWSGIWrapper:
    """Vercel Serverless rewrite 환경에서 원래 요청 URL(PATH_INFO)을 정상 복원하는 WSGI 미들웨어"""
    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        query_string = environ.get("QUERY_STRING", "")
        extracted_path = None

        # 1. vercel.json rewrite에서 전달된 __vercel_path__ 추출
        if "__vercel_path__=" in query_string:
            params = parse_qs(query_string, keep_blank_values=True)
            if "__vercel_path__" in params and params["__vercel_path__"]:
                extracted_path = params["__vercel_path__"][0]
                del params["__vercel_path__"]
                environ["QUERY_STRING"] = urlencode(params, doseq=True)

        # 2. Vercel 원본 요청 헤더 폴백 확인
        header_path = (
            environ.get("HTTP_X_VERCEL_ORIGINAL_PATH")
            or environ.get("HTTP_X_FORWARDED_URI")
        )
        if header_path:
            header_path = header_path.split("?")[0]

        target_path = extracted_path or header_path

        if target_path:
            clean_path = target_path.split("?")[0]
            while clean_path.startswith("//"):
                clean_path = clean_path[1:]
            if not clean_path.startswith("/"):
                clean_path = "/" + clean_path
            environ["PATH_INFO"] = clean_path
        else:
            current_path = environ.get("PATH_INFO", "")
            if current_path in ("/api/index", "/api/index.py", "/api", "/api/"):
                environ["PATH_INFO"] = "/"

        return self.wsgi_app(environ, start_response)

flask_app.wsgi_app = VercelWSGIWrapper(flask_app.wsgi_app)
app = flask_app
