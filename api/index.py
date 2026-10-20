import os
import sys

# Vercel Serverless 실행 환경에서 프로젝트 루트 경로를 sys.path에 등록
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

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
                raw_p = params["__vercel_path__"][0]
                if raw_p and not raw_p.startswith(":"):
                    extracted_path = raw_p
                del params["__vercel_path__"]
                environ["QUERY_STRING"] = urlencode(params, doseq=True)

        # 2. Vercel 원본 요청 헤더 폴백 확인
        header_path = (
            environ.get("HTTP_X_VERCEL_ORIGINAL_PATH")
            or environ.get("REQUEST_URI")
            or environ.get("RAW_URI")
            or environ.get("HTTP_X_FORWARDED_URI")
            or environ.get("HTTP_X_ORIGINAL_URI")
        )

        target_path = extracted_path or header_path or environ.get("PATH_INFO", "")

        # 쿼리 파라미터 분리
        if target_path and "?" in target_path:
            target_path = target_path.split("?")[0]

        # api/index 직접 호출이거나 빈 경로일 경우 루트('/')로 복원
        if not target_path or target_path in ("/api/index", "/api/index.py", "/api", "/api/", "/index.py", "/index"):
            target_path = "/"
        elif target_path.startswith("/api/index/"):
            target_path = "/" + target_path[len("/api/index/"):]

        # 이중 슬래시 정규화 및 시작 슬래시 보장
        while target_path.startswith("//"):
            target_path = target_path[1:]
        if not target_path.startswith("/"):
            target_path = "/" + target_path

        environ["PATH_INFO"] = target_path
        environ["SCRIPT_NAME"] = ""
        return self.wsgi_app(environ, start_response)

flask_app.wsgi_app = VercelWSGIWrapper(flask_app.wsgi_app)
app = flask_app
