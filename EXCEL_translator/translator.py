import os
import time
import hashlib
import yaml
import requests

LANG_PAIRS = {
    "zh-fr": ("zh", "fr"),
    "fr-zh": ("fr", "zh"),
    "en-fr": ("en", "fr"),
    "fr-en": ("fr", "en")
}

DEEPL_API_URL = "https://api-free.deepl.com/v2/translate"
TERMS_YAML_PATH = os.path.join(os.path.dirname(__file__), "term_dict.yaml")
translation_cache = {}

def load_term_dict():
    if not os.path.exists(TERMS_YAML_PATH):
        return {}, "⚠️ 未找到术语词典 term_dict.yaml，将不会应用术语翻译。"
    with open(TERMS_YAML_PATH, 'r', encoding='utf-8') as f:
        raw_terms = yaml.safe_load(f)
    if not raw_terms:
        return {}, "⚠️ 术语词典 term_dict.yaml 内容为空，将不会应用术语翻译。"
    return raw_terms, None

TERM_DICT, TERM_DICT_WARNING = load_term_dict()
if TERM_DICT_WARNING:
    print(TERM_DICT_WARNING)

import re
def apply_term_dict(text, src_lang, tgt_lang):
    if not isinstance(text, str) or not TERM_DICT:
        return text

    for term in TERM_DICT.values():
        zh = term.get("zh", "")
        fr_list = term.get("fr", [])
        en_list = term.get("en", [])

        if src_lang == "zh" and tgt_lang == "fr":
            if zh and fr_list:
                text = text.replace(zh, fr_list[0])

        elif src_lang == "fr" and tgt_lang == "zh":
            for fr in fr_list:
                text = text.replace(fr, zh)

        elif src_lang == "zh" and tgt_lang == "en":
            if zh and en_list:
                text = text.replace(zh, en_list[0])

        elif src_lang == "en" and tgt_lang == "zh":
            for en in en_list:
                text = text.replace(en, zh)

    return text
def cache_key(text, engine, lang_pair):
    return hashlib.md5(f"{engine}_{lang_pair}_{text}".encode("utf-8")).hexdigest()

def translate_cell_text(text, engine="deepl", lang_pair="zh-fr", apikeys=None, max_retries=3, log_func=None):
    if not text or str(text).strip() == "":
        return text

    src, dest = LANG_PAIRS.get(lang_pair, ("zh", "fr"))
    text = apply_term_dict(text, src, dest)

    key = cache_key(text, engine, lang_pair)
    if key in translation_cache:
        return translation_cache[key]

    retries = 0
    result = text

    while retries < max_retries:
        try:
            if engine == "deepl":
                deepl_key = apikeys.get("deepl", "")
                if not deepl_key:
                    raise ValueError("缺少 DeepL API 密钥")
                url = DEEPL_API_URL
                data = {
                    "auth_key": deepl_key,
                    "text": text,
                    "source_lang": src.upper(),
                    "target_lang": dest.upper()
                }
                resp = requests.post(url, data=data, timeout=10)
                result = resp.json()["translations"][0]["text"]
                break

            else:
                raise ValueError(f"未知翻译引擎：{engine}")

        except Exception as e:
            retries += 1
            msg = f"⚠️ 翻译失败 [{engine}] 第{retries}次: {text[:30]}... -> {e}"
            if log_func:
                log_func(msg)
            else:
                print(msg)
            time.sleep(1.5)

    translation_cache[key] = result
    return result
