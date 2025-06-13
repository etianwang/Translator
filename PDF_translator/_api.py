import requests

class DoclingoAPI:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.headers = {
            "Authorization": f"Bearer {self.api_key}"
        }

    def submit_translation_new(self, file_path, target_lang, model="chatgpt-4omini", ocr_flag=0, source_lang=None):
        url = "https://api.doclingo.cn/api/core/external/translate"
        with open(file_path, "rb") as f:
            files = {"file": f}
            data = {
                "targetLang": target_lang,
                "model": model,
                "ocrFlag": ocr_flag,
                "mathFlag": 1  # ✅ 建议总是开启公式识别
            }
            if source_lang:
                data["sourceLang"] = source_lang  # 比如 'zh-CN'
            response = requests.post(url, headers=self.headers, files=files, data=data)
            response.raise_for_status()
            result = response.json()
            if result.get("success") and "data" in result:
                return result["data"]["translateQueryKey"]
            else:
                raise RuntimeError(f"API 返回异常：{result}")
            
    def check_translation_status(self, query_key):
        url = f"https://api.doclingo.cn/api/core/external/trans/query?translateQueryKey={query_key}"
        response = requests.get(url, headers=self.headers)
        response.raise_for_status()
        result = response.json()
        if result.get("success") and "data" in result:
            return result["data"]
        else:
            raise RuntimeError(f"状态查询失败：{result}")
