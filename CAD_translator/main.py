import ezdxf
import re
import time
import os
import shutil
import csv
from pathlib import Path
from googletrans import Translator
import deepl
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import queue
from datetime import datetime
import os
import sys
import urllib.request
import unicodedata
import json
import winreg
from text_cleaning_utils import TextCleaner
import yaml

def resource_path(relative_path):
    """
    获取资源文件路径，兼容开发环境和 PyInstaller 打包后的路径。
    """
    try:
        base_path = sys._MEIPASS  # PyInstaller 临时目录
    except AttributeError:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def load_yaml_data(filename):
    full_path = resource_path(filename)
    if os.path.exists(full_path):
        with open(full_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    return {}

def get_installed_fonts():
    fonts = set()
    try:
        reg_path = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, reg_path) as key:
            for i in range(0, winreg.QueryInfoKey(key)[1]):
                name, _, _ = winreg.EnumValue(key, i)
                fonts.add(name.split(" (")[0].strip())
    except Exception as e:
        print(f"获取字体失败: {e}")
    return fonts
preferred_fonts = [
    "SimSun",        # 宋体，Win默认有
    "Microsoft YaHei",  # 微软雅黑，清晰
    "SimHei",        # 黑体
    "Arial Unicode MS", # 英文+中文兼容
    "Arial",
    "Tahoma",
]

def pick_available_font():
    installed_fonts = get_installed_fonts()
    for font in preferred_fonts:
        if font in installed_fonts:
            return font
    return "Arial"  # 默认 fallback


CONFIG_PATH = os.path.expanduser("~/.cad_translator_config.json")

def remove_emoji(text):
    import re
    emoji_pattern = re.compile(
        "["
        u"\U0001F600-\U0001F64F"  # emoticons
        u"\U0001F300-\U0001F5FF"  # symbols & pictographs
        u"\U0001F680-\U0001F6FF"  # transport & map symbols
        u"\U0001F1E0-\U0001F1FF"  # flags
        u"\U00002702-\U000027B0"  # dingbats
        u"\U000024C2-\U0001F251"  # enclosed characters
        "]+",
        flags=re.UNICODE
    )
    return emoji_pattern.sub(r'', text)
def resource_path(relative_path):
    """返回资源文件的正确路径（兼容 .py 和 .exe）"""
    try:
        base_path = sys._MEIPASS  # PyInstaller 临时目录
    except AttributeError:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

class CADChineseTranslator:

    @staticmethod
    def contains_surrogates(text):
        """检测是否包含 Unicode surrogate（代理）字符"""
        return any(0xD800 <= ord(c) <= 0xDFFF for c in text)
    def fully_clean_for_write(self, text):
        try:
            cleaned = self.cleaner.full_clean(text)
            return cleaned.encode("utf-8", "ignore").decode("utf-8")
        except Exception as e:
            return f"[完全清洗失败: {e}]"

    def __init__(self, log_callback=None):
        self.translator = Translator()
        self.translated_cache = {}
        self.default_font = pick_available_font()
        self.log_callback = log_callback
        self.use_engine = 'google'  # 默认引擎，可选：'google'、'deepl'、'chatgpt'
        self.deepl_api_key = os.environ.get("DEEPL_API_KEY")  # 或你手动赋值
        self.deepl_translator = None
        self.cleaner = TextCleaner()
        abbrev_data = load_yaml_data("translation_abbreviations.yaml")
        self.abbrev_map_fr_to_zh = abbrev_data.get("abbrev_map", {})

        # if self.deepl_api_key:
        #     try:
        #         self.deepl_translator = deepl.Translator(self.deepl_api_key)
        #         self.safe_log(" DeepL 引擎已就绪")
        #     except Exception as e:
        #         self.safe_log(f" 初始化 DeepL 失败: {e}")
        # 语言配置 - 只保留中法互译
# 加载上下文与修正表
        context_zh_to_fr = load_yaml_data("translation_context.yaml").get("context_zh_to_fr", {})
        context_fr_to_zh = load_yaml_data("translation_context_fr_to_zh.yaml").get("context_fr_to_zh", {})
        corrections_fr_to_zh = load_yaml_data("translation_corrections.yaml").get("corrections_fr_to_zh", {})

        self.context_zh_to_fr = context_zh_to_fr
        self.context_fr_to_zh = context_fr_to_zh
        self.corrections_fr_to_zh = corrections_fr_to_zh

        self.language_configs = {
            'zh_to_fr': {
                'source': 'zh-cn',
                'target': 'fr',
                'name': '中文→法语',
                'context': self.context_zh_to_fr
            },
            'fr_to_zh': {
                'source': 'fr',
                'target': 'zh-cn',
                'name': '法语→中文',
                'context': self.context_fr_to_zh
            }
        }
        self.chatgpt_api_key = None  # placeholder
        # 如果传入了 deepl_key 后初始化 translator：
        if self.deepl_api_key:
            try:
                self.deepl_translator = deepl.Translator(self.deepl_api_key)
                self.safe_log(" DeepL 引擎初始化成功")
            except Exception as e:
                self.safe_log(f" DeepL 初始化失败: {e}")
    @property
    def deepl_api_key(self):
        return self._deepl_api_key

    @deepl_api_key.setter
    def deepl_api_key(self, value):
        self._deepl_api_key = value
        if value:
            try:
                import deepl
                self.deepl_translator = deepl.Translator(value)
            except Exception as e:
                self.safe_log(f" DeepL 初始化失败: {e}")    
    def safe_log(self, message):
        if not self.log_callback:
            print("[无日志回调]:", message)
            return
        try:
            cleaned = self.cleaner.clean_for_log(message)
            self.log_callback(cleaned)
        except Exception as e:
            print("[日志记录失败]", e)
            print("原始日志内容:", repr(message))

    def preprocess_abbreviations(self, text, lang_config_key):
        """在翻译前处理常见缩写，例如 W:800mm → 宽度:800mm，W400*H650 → 宽度400×高度650"""
        if not text or not isinstance(text, str):
            return text

        if lang_config_key == 'fr_to_zh':
            # 缩写映射
            abbrev_map = self.abbrev_map_fr_to_zh

            # 处理纯楼层标识 B2 → 负二楼
            if text.strip().upper() in abbrev_map:
                return abbrev_map[text.strip().upper()]

            # 处理类似 W:800mm 格式
            pattern = re.compile(r'\b([WHDL])\s*[:：]\s*(\d+\.?\d*\s*(?:mm|cm|m)?)', re.IGNORECASE)
            text = pattern.sub(lambda m: f"{abbrev_map.get(m.group(1).upper(), m.group(1))}:{m.group(2)}", text)

            # 处理类似 W400*H650 或 H650*W400 格式
            pattern_pair = re.compile(r'\b([WHDL])\s*(\d+)\s*[*×x]\s*([WHDL])\s*(\d+)', re.IGNORECASE)
            def replace_pair(match):
                key1 = match.group(1).upper()
                val1 = match.group(2)
                key2 = match.group(3).upper()
                val2 = match.group(4)
                name1 = abbrev_map.get(key1, key1)
                name2 = abbrev_map.get(key2, key2)
                return f"{name1}{val1}×{name2}{val2}"
            text = pattern_pair.sub(replace_pair, text)
        return text

    def log(self, message):
        """发送日志消息到GUI"""
        if self.log_callback:
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.log_callback(f"[{timestamp}] {message}")

    def get_contextual_translation(self, text, lang_config_key):
        """根据语言配置获取上下文翻译提示"""
        if lang_config_key not in self.language_configs:
            return text
            
        context_dict = self.language_configs[lang_config_key]['context']
        hints = [f"{term}={trans}" for term, trans in context_dict.items() if term in text]
        if hints:
            return f"建筑术语: {'; '.join(hints[:3])}."
        return text
    
    def post_process_translation(self, text, original, lang_config_key):
        if '建筑术语:' in text and '原文:' in text:
            text = text.split('原文:')[-1].strip()
        text = re.sub(r'.*术语[：:][^.]*\.\s*', '', text)

        corrections = {}

        if lang_config_key == 'zh_to_fr':
            corrections = {
                'variole': 'plafond',
                'virus du plafond': 'plafond',
                'maladie du plafond': 'plafond',
                'plan de variole': 'plan de plafond',
                'fleur de plafond': 'plafond',
                'toilettes salle de bain': 'salle de bain',
                'cuisine cuisine': 'cuisine',
                'écran de contrôle': 'écran de contrôle',
                'contrôle': 'contrôle',
            }

        elif lang_config_key == 'fr_to_zh':
            corrections = self.corrections_fr_to_zh  # <-- 来自 YAML 文件

        # 替换所有定义的错误词
        for wrong, right in corrections.items():
            text = re.sub(rf'\b{re.escape(wrong)}\b', right, text)

        return re.sub(r'\s+', ' ', text).strip()
   
    def translate_text(self, text, lang_config_key):
        if not text or not lang_config_key:
            return text

        # Step 1: 预清洗
        cleaned = self.cleaner.full_clean(text)

        if text in self.translated_cache:
            return self.translated_cache[text]

        if not cleaned.strip():
            self.safe_log(f"跳过空文本或无效文本: \"{text}\"")
            return self.cleaner.safe_utf8(text)

        try:
            cleaned.encode('utf-8')
        except UnicodeEncodeError as e:
            self.safe_log(f"跳过包含编码问题的文本: \"{text}\" - 错误: {e}")
            return self.cleaner.safe_utf8(text)

        # Step 2: 判定是否跳过翻译
        non_translatable = re.fullmatch(r'[\d\s.,:;*×x\-_/\\%°(){}\[\]]+', cleaned.strip())
        ascii_only = all(ord(c) < 128 for c in cleaned.strip())
        non_word_ratio = sum(1 for c in cleaned if not c.isalnum()) / (len(cleaned) or 1)

        if non_translatable or (ascii_only and non_word_ratio > 0.6):
            self.safe_log(f"跳过非翻译文本（符号/ASCII）: \"{cleaned}\"")
            self.translated_cache[text] = cleaned
            return self.cleaner.safe_utf8(cleaned)

        # Step 3: 缩写处理 & 中文校验
        cleaned = self.preprocess_abbreviations(cleaned, lang_config_key)
        cleaned = self.cleaner.safe_utf8(cleaned)

        if lang_config_key == "zh_to_fr" and not re.search(r'[\u4e00-\u9fff]', cleaned):
            self.safe_log(f"跳过非中文内容（疑似编号）: \"{cleaned}\"")
            return self.cleaner.safe_utf8(text)

        # Step 4: 可读性检查
        printable_chars = sum(1 for char in cleaned if char.isprintable() or '\u4e00' <= char <= '\u9fff')
        if len(cleaned) > 0 and printable_chars / len(cleaned) < 0.5:
            self.safe_log(f"跳过损坏文本(可读字符比例过低): \"{cleaned}\"")
            return self.cleaner.safe_utf8(text)

        if lang_config_key not in self.language_configs:
            self.safe_log(f"无效的翻译配置: {lang_config_key}")
            return self.cleaner.safe_utf8(text)

        lang_config = self.language_configs[lang_config_key]

        try:
            context = self.get_contextual_translation(cleaned, lang_config_key)
            self.safe_log(f"翻译中 ({lang_config['name']}): {cleaned}")
            if context != cleaned:
                self.safe_log(f"提示术语: {context}")

            # Step 5: 发送翻译请求
            translated_result = ""
            if self.use_engine == 'google':
                result = self.translator.translate(cleaned, src=lang_config['source'], dest=lang_config['target'])
                translated_result = result.text
            elif self.use_engine == 'deepl':
                deepl_result = self.deepl_translator.translate_text(
                    cleaned,
                    source_lang=lang_config['source'].split('-')[0].upper(),
                    target_lang=lang_config['target'].split('-')[0].upper()
                )
                translated_result = deepl_result.text
            elif self.use_engine == 'chatgpt':
                if not self.chatgpt_api_key:
                    raise Exception("ChatGPT API Key 未配置")

                import openai
                openai.api_key = self.chatgpt_api_key

                try:
                    prompt = f"请将以下内容从{lang_config['name']}翻译成对应语言，不要解释：\n\"{cleaned}\""
                    response = openai.ChatCompletion.create(
                        model="gpt-3.5-turbo",
                        messages=[
                            {"role": "user", "content": prompt}
                        ],
                        temperature=0.2
                    )
                    translated_result = response.choices[0].message['content'].strip()
                except Exception as e:
                    raise Exception(f"ChatGPT 翻译失败: {e}")
            else:
                raise Exception("未配置可用的翻译引擎")

            # Step 6: 翻译结果后处理
            if self.contains_surrogates(translated_result):
                self.safe_log(f"⚠ 翻译结果含代理字符，准备清理: {repr(translated_result)}")
                translated_result = self.cleaner.full_clean(translated_result)

            final = self.post_process_translation(translated_result, cleaned, lang_config_key)
            final = self.cleaner.safe_utf8(final)
            final = self.cleaner.full_clean(final)
            final = self.cleaner.safe_utf8(final).strip()  # ✨ 此处加入 strip

            if self.contains_surrogates(final):
                self.safe_log(f"⚠ 最终翻译仍包含代理字符，将用占位符替换: {repr(final)}")
                final = final.replace('\ufffd', '?')  # 防止乱码
                final = self.cleaner.safe_utf8(final)

            self.translated_cache[text] = final
            self.safe_log(f"✔ 翻译完成 ({self.use_engine}): \"{cleaned}\" → \"{final}\"")
            time.sleep(0.5)
            return final

        except Exception as e:
            self.safe_log(f"翻译失败 ({self.use_engine}): {e} → 原文: \"{cleaned}\"")
            fallback = self.cleaner.full_clean(self.cleaner.safe_utf8(text))
            return fallback


    def extract_text_entities(self, doc, lang_config, include_blocks=False):
        """提取所有文本实体，增强编码检查"""
        items = []
        # 处理模型空间和布局空间
        for space in [doc.modelspace()] + list(doc.layouts):
            for e in space:
                if e.dxftype() in ['TEXT', 'MTEXT']:
                    txt = self.get_entity_text(e)
                    if txt and self.is_valid_text_for_translation(txt):
                        items.append({
                            'entity': e,
                            'original_text': txt,
                            'layer': getattr(e.dxf, 'layer', 'DEFAULT'),
                            'location': space.name if hasattr(space, 'name') else 'modelspace'
                        })

        # 根据选项决定是否处理块内文字
        if include_blocks:
            self.safe_log("选择翻译块内文字，正在处理块...")
            for block in doc.blocks:
                if block.name.startswith('*'):
                    continue
                for e in block:
                    if e.dxftype() in ['TEXT', 'MTEXT']:
                        txt = self.get_entity_text(e)
                        if txt and self.is_valid_text_for_translation(txt):
                            items.append({
                                'entity': e,
                                'original_text': txt,
                                'layer': getattr(e.dxf, 'layer', 'DEFAULT'),
                                'location': f'block:{block.name}'
                            })
        else:
            self.safe_log("跳过块内文字翻译（推荐设置）")

        self.safe_log(f"提取文本实体: {len(items)} 条 {'(包含块内文字)' if include_blocks else '(不包含块内文字)'}")
        return items

    def is_valid_text_for_translation(self, text):
        """检查文本是否适合翻译（增强编码检查）"""
        if not text or not text.strip():
            return False

        cleaned = self.cleaner.full_clean(text)

        if not cleaned.strip():
            return False

        # 检查是否包含无效字符
        invalid_chars = sum(1 for char in cleaned if not self.cleaner.is_valid_char(char))
        if invalid_chars > 0:
            self.safe_log(f"发现 {invalid_chars} 个无效字符，跳过文本: \"{text[:20]}...\"")
            return False

        # 检查可读性
        printable_chars = sum(1 for char in cleaned if (
            char.isprintable() or 
            char.isspace() or 
            '\u4e00' <= char <= '\u9fff'
        ))
        if len(cleaned) > 0 and printable_chars / len(cleaned) < 0.8:
            return False

        return True
    def get_entity_text(self, entity):
        try:
            if hasattr(entity.dxf, 'text'):
                text = entity.dxf.text
            elif hasattr(entity, 'text'):
                text = entity.text
            else:
                return ""
            
            # 安全解码获取的文本
            decoded = self.cleaner.full_clean(text)
            
            # 如果解码后为空或无效，记录警告
            if not decoded or decoded != text:
                self.safe_log(f"文本解码修复: \"{text}\" → \"{decoded}\"")
            decoded = self.cleaner.full_clean(text, debug=True, log_func=self.safe_log)
            return decoded
        except Exception as e:
            self.safe_log(f"获取文本失败: {e}")
            return ""
    #  写回翻译后的文本到实体
    def write_back_translation(self, entity, new_text):
        try:
            cleaned_text = self.fully_clean_for_write(new_text)
            self.safe_log(f"准备写入文本: {repr(cleaned_text)}")
            self.safe_log(f"是否包含代理字符: {any(0xD800 <= ord(c) <= 0xDFFF for c in cleaned_text)}")

            if entity.dxftype() == "TEXT":
                entity.dxf.text = cleaned_text
            elif entity.dxftype() == "MTEXT":
                font = getattr(self, 'default_font', 'SimSun')
                formatted = fr"{{\\f{font}|b0|i0|c134;{cleaned_text}}}"
                entity.text = formatted
                entity.dxf.text = formatted
            else:
                self.safe_log(f" 未知实体类型: {entity.dxftype()}，无法写入文本")

        except Exception as e:
            self.safe_log(f"写回失败: {e}")

    def create_report(self, items, output_csv):
        """创建CSV报告，确保输出文件使用UTF-8编码"""
        try:
            with open(output_csv, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.DictWriter(f, fieldnames=['layer', 'location', 'original_text', 'translated_text'])
                writer.writeheader()
                for item in items:
                    try:
                        row = {
                            'layer': self.fully_clean_for_write(item.get('layer', '')),
                            'location': self.fully_clean_for_write(item.get('location', '')),
                            'original_text': self.fully_clean_for_write(item.get('original_text', '')),
                            'translated_text': self.fully_clean_for_write(item.get('translated_text', '')),
                        }
                        writer.writerow(row)
                    except Exception as line_err:
                        self.safe_log(f" 写入一行报告时出错: {line_err}")
                        continue
        except Exception as file_err:
            self.safe_log(f" 创建 CSV 文件失败: {file_err}")
    def translate_cad_file(self, input_file, output_file, lang_config, include_blocks=False):
        self.safe_log(f"正在读取: {input_file}")
        self.safe_log(f"当前写入字体: {self.default_font}")
        # 尝试不同的编码方式读取文件
        doc = None
        encodings_to_try = ['utf-8', 'gbk', 'gb2312', 'cp1252']
        
        for encoding in encodings_to_try:
            try:
                self.safe_log(f"尝试使用 {encoding} 编码读取文件...")
                doc = ezdxf.readfile(input_file, encoding=encoding)
                self.safe_log(f"成功使用 {encoding} 编码读取文件")
                break
            except Exception as e:
                self.safe_log(f"使用 {encoding} 编码失败: {e}")
        
        if doc is None:
            raise Exception("无法使用任何编码方式读取DXF文件")
        #  在提取之前清理一次（防止含非法字符的实体阻断提取）
        self.clean_all_entities(doc)


        #  然后提取文本进行翻译
        items = self.extract_text_entities(doc, lang_config, include_blocks)

        #  放到此处：确保 doc 已成功读取后再进行代理字符检查
        for e in doc.modelspace():
            if e.dxftype() in ['TEXT', 'MTEXT']:
                content = getattr(e.dxf, 'text', '') or getattr(e, 'text', '')
                if any(0xD800 <= ord(c) <= 0xDFFF for c in content):
                    self.safe_log(f" 最终写入前仍检测到代理字符: {repr(content)}")

        if lang_config and lang_config in self.language_configs:
            config_name = self.language_configs[lang_config]['name']
            self.safe_log(f"翻译模式: {config_name}")

        total_items = len(items)
        successful_translations = 0
        skipped_invalid = 0

        for i, item in enumerate(items, 1):
            original_text = item['original_text']

            if not self.is_valid_text_for_translation(original_text):
                skipped_invalid += 1
                self.safe_log(f"跳过无效文本 ({i}/{total_items}): \"{original_text[:30]}...\"")
                item['translated_text'] = original_text
                continue

            translated = self.translate_text(original_text, lang_config)
            item['translated_text'] = translated

            if translated != original_text:
                self.write_back_translation(item['entity'], translated)
                successful_translations += 1

            self.safe_log(f"进度: {i}/{total_items} ({i/total_items*100:.1f}%)")
        #  保存前强制清理所有残留代理字符
        self.safe_log(" 最终保存前，强制清理所有文本实体中的非法字符")

        def clean_entities(container, label="modelspace"):
            for e in container:
                if e.dxftype() in ['TEXT', 'MTEXT', 'ATTDEF', 'ATTRIB', 'DIMENSION']:  # 全部纳入处理
                    raw_text = getattr(e.dxf, 'text', '') or getattr(e, 'text', '')
                    if raw_text:
                        cleaned = self.cleaner.full_clean(raw_text)
                        if cleaned != raw_text:
                            self.safe_log(f" 清理后替换文本 ({label}): '{raw_text[:30]}' → '{cleaned[:30]}'")
                            try:
                                if hasattr(e.dxf, 'text'):
                                    e.dxf.text = cleaned
                                elif hasattr(e, 'text'):
                                    e.text = cleaned
                            except Exception as ee:
                                self.safe_log(f" 写回失败 ({label}): {ee}")

        # 清理 modelspace
        clean_entities(doc.modelspace(), "modelspace")

        # 清理 layouts（paper space 等）
        for layout in doc.layouts:
            clean_entities(layout, f"layout:{layout.name}")

        # 清理 blocks（即使你没翻译 block，也要防止残留非法字符）
        for block in doc.blocks:
            clean_entities(block, f"block:{block.name}")
            #  翻译后再次清理（防止翻译引擎返回代理字符）
        self.clean_all_entities(doc)
        try:
            doc.saveas(output_file, encoding='utf-8')
            self.safe_log(f" 文件成功保存: {output_file}")
        except UnicodeEncodeError as e:
            self.safe_log(f" 文件保存失败: {e}")
            messagebox.showerror("保存失败", f"文件保存出错：\n{e}")

        report_file = output_file.replace('.dxf', '_report.csv')
        self.create_report(items, report_file)
        self.safe_log(f"翻译报告保存: {report_file}")
        self.safe_log(f"翻译完成！共处理 {total_items} 个文本对象")
        self.safe_log(f"成功翻译: {successful_translations} 个，跳过无效文本: {skipped_invalid} 个")
    def clean_all_entities(self, doc):
        self.safe_log(" 清理所有实体中的非法字符")

        def clean_container(container, label):
            for e in container:
                if e.dxftype() in ['TEXT', 'MTEXT', 'ATTDEF', 'ATTRIB', 'DIMENSION']:
                    raw = getattr(e.dxf, 'text', '') or getattr(e, 'text', '')
                    if raw and any(0xD800 <= ord(c) <= 0xDFFF for c in raw):
                        cleaned = self.cleaner.full_clean(raw)
                        if cleaned != raw:
                            self.safe_log(f" 清理后替换文本 ({label}): '{raw[:30]}' → '{cleaned[:30]}'")
                            try:
                                if hasattr(e.dxf, 'text'):
                                    e.dxf.text = cleaned
                                elif hasattr(e, 'text'):
                                    e.text = cleaned
                            except Exception as ee:
                                self.safe_log(f" 写回失败 ({label}): {ee}")

        clean_container(doc.modelspace(), "modelspace")
        for layout in doc.layouts:
            clean_container(layout, f"layout:{layout.name}")
        for block in doc.blocks:
            clean_container(block, f"block:{block.name}")

# GUI类保持不变，只需要更新版本号
class CADTranslatorGUI:
    def __init__(self):
        self.log_text = None
        self.root = tk.Tk()
        self.root.title("Honsen内部 CAD中法互译工具 v2.2 - 编码问题修复版")
        self.root.geometry("850x750")
        self.root.resizable(True, True)
        self.cleaner = TextCleaner()
        try:
            icon_path = resource_path("ico.ico")
            self.root.iconbitmap(icon_path)
        except:
            pass  # 如果图标文件不存在，忽略错误
        self.deepl_key = tk.StringVar()
        self.chatgpt_key = tk.StringVar()
        # 日志队列
        self.log_queue = queue.Queue()
        
        # 变量
        self.input_file = tk.StringVar()
        self.output_dir = tk.StringVar()
        now = datetime.now()
        default_filename = f"translated_cad_{now.strftime('%Hh%M_%d-%m-%y')}"
        self.output_name = tk.StringVar(value=default_filename)
        self.translate_blocks = tk.BooleanVar(value=False)  # 默认不翻译块内文字
        self.translation_mode = tk.StringVar(value='zh_to_fr')  # 默认中文→法语
        self.load_api_keys()
        self.setup_ui()
        self.check_log_queue()
    def _create_translator(self):
        translator = CADChineseTranslator(log_callback=self.log_message)
        translator.use_engine = self.translation_engine.get().strip()
        translator.deepl_api_key = self.deepl_key.get().strip()
        translator.chatgpt_api_key = self.chatgpt_key.get().strip()
        return translator
    def safe_text_for_tkinter(self, text):
        """
        过滤超出tkinter支持范围的Unicode字符
        tkinter在某些版本中不支持U+FFFF以上的字符（如emoji）
        """
        if not text:
            return ""
        
        safe_chars = []
        for char in text:
            # 过滤超出BMP（基本多文种平面）的字符
            if ord(char) <= 0xFFFF:
                safe_chars.append(char)
            else:
                # 将不支持的字符替换为方括号描述
                char_name = f"[U+{ord(char):04X}]"
                safe_chars.append(char_name)
        
        return ''.join(safe_chars)
        
    def setup_ui(self):
        # 主容器
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        
        # 创建标签页控件
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill='both', expand=True, padx=10, pady=10)
        
        # 创建翻译功能页面
        self.translation_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.translation_frame, text='翻译功能')
        
        # 创建版本日志页面
        self.changelog_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.changelog_frame, text='版本更新日志')
        
        # 设置翻译功能页面
        self.setup_translation_tab()
        
        # 设置版本日志页面
        self.setup_changelog_tab()
        
    def setup_translation_tab(self):
        main_frame = ttk.Frame(self.translation_frame, padding="10")
        main_frame.pack(fill='both', expand=True)
        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(7, weight=1)

        title_label = tk.Label(main_frame, text="Honsen非洲内部 CAD中法互译工具 v2.2\n编码问题修复版 - 先将dwg文件转换为dxf文件", 
                            font=('宋体', 16, 'bold'))
        title_label.grid(row=0, column=0, columnspan=3, pady=(0, 20))

        ttk.Label(main_frame, text="选择dxf文件:").grid(row=1, column=0, sticky=tk.W, pady=5)
        ttk.Entry(main_frame, textvariable=self.input_file, width=50).grid(
            row=1, column=1, sticky=(tk.W, tk.E), pady=5, padx=(5, 5))
        ttk.Button(main_frame, text="浏览", command=self.browse_input_file).grid(row=1, column=2, pady=5)

        ttk.Label(main_frame, text="输出目录:").grid(row=2, column=0, sticky=tk.W, pady=5)
        ttk.Entry(main_frame, textvariable=self.output_dir, width=50).grid(
            row=2, column=1, sticky=(tk.W, tk.E), pady=5, padx=(5, 5))
        ttk.Button(main_frame, text="浏览", command=self.browse_output_dir).grid(row=2, column=2, pady=5)

        ttk.Label(main_frame, text="输出文件名:").grid(row=3, column=0, sticky=tk.W, pady=5)
        name_frame = ttk.Frame(main_frame)
        name_frame.grid(row=3, column=1, sticky=(tk.W, tk.E), pady=5, padx=(5, 5))
        name_frame.columnconfigure(0, weight=1)
        ttk.Entry(name_frame, textvariable=self.output_name).grid(row=0, column=0, sticky=(tk.W, tk.E), padx=(0, 5))
        ttk.Label(name_frame, text=".dxf").grid(row=0, column=1)

        options_api_container = ttk.Frame(main_frame)
        options_api_container.grid(row=4, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=10)
        options_api_container.columnconfigure(0, weight=1)
        options_api_container.columnconfigure(1, weight=1)

        options_frame = ttk.LabelFrame(options_api_container, text="翻译选项", padding="10")
        options_frame.grid(row=0, column=0, sticky=(tk.N, tk.EW), padx=(0, 10))

        ttk.Label(options_frame, text="翻译模式:").grid(row=0, column=0, sticky=tk.W, pady=5)
        mode_frame = ttk.Frame(options_frame)
        mode_frame.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=(10, 0))
        ttk.Radiobutton(mode_frame, text="中文→法语", variable=self.translation_mode, value='zh_to_fr').grid(row=0, column=0, sticky=tk.W)
        ttk.Radiobutton(mode_frame, text="法语→中文", variable=self.translation_mode, value='fr_to_zh').grid(row=0, column=1, sticky=tk.W, padx=(15, 0))

        ttk.Checkbutton(options_frame, text="翻译CAD块(Block)内的文字", variable=self.translate_blocks).grid(row=1, column=0, columnspan=2, sticky=tk.W, pady=(10, 0))
        note_label = tk.Label(options_frame, text="注意：块内文字通常是标准图块符号，建议保持原样", font=('宋体', 9), fg='gray')
        note_label.grid(row=2, column=0, columnspan=2, sticky=tk.W, pady=(5, 0))

        ttk.Label(options_frame, text="翻译引擎:").grid(row=4, column=0, sticky=tk.W, pady=5)
        self.translation_engine = tk.StringVar(value='google')
        engine_dropdown = ttk.Combobox(options_frame, textvariable=self.translation_engine, state='readonly', values=['google', 'deepl', 'chatgpt'], width=20)
        engine_dropdown.grid(row=4, column=1, sticky=tk.W)
        engine_note = tk.Label(options_frame, text="DeepL/ChatGPT 需配置 API Key", font=('宋体', 9), fg='gray')
        engine_note.grid(row=5, column=0, columnspan=2, sticky=tk.W)

        api_frame = ttk.LabelFrame(options_api_container, text="API Key 设置（可选）", padding="10")
        api_frame.grid(row=0, column=1, sticky=(tk.N, tk.EW))
        ttk.Label(api_frame, text="DeepL API Key:").grid(row=0, column=0, sticky=tk.W, pady=3)
        ttk.Entry(api_frame, textvariable=self.deepl_key, width=40, show="*").grid(
            row=0, column=1, sticky=(tk.W, tk.E), padx=5
        )
        ttk.Label(api_frame, text="ChatGPT API Key:").grid(row=1, column=0, sticky=tk.W, pady=3)
        ttk.Entry(api_frame, textvariable=self.chatgpt_key, width=40, show="*").grid(
            row=1, column=1, sticky=(tk.W, tk.E), padx=5
        )
        self.deepl_key.trace_add("write", lambda *args: self.save_api_keys())
        self.chatgpt_key.trace_add("write", lambda *args: self.save_api_keys())

        # 添加按钮组到 api_frame 下方
        style = ttk.Style()
        style.configure("Big.TButton", font=("Microsoft YaHei", 12, "bold"))

        button_frame = ttk.Frame(api_frame)
        button_frame.grid(row=2, column=0, columnspan=2, pady=(12, 0), sticky=tk.W)

        self.start_button = ttk.Button(
            button_frame, text="开始翻译", command=self.start_translation, style="Big.TButton"
        )
        self.start_button.pack(side=tk.LEFT, padx=(0, 10), ipady=4)

        ttk.Button(button_frame, text="清除日志", command=self.clear_log).pack(side=tk.LEFT)


        self.progress = ttk.Progressbar(main_frame, mode='indeterminate')
        self.progress.grid(row=6, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=10)

        log_frame = ttk.LabelFrame(main_frame, text="实时日志", padding="5")
        log_frame.grid(row=7, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S), pady=10)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        main_frame.rowconfigure(7, weight=1)
        font = pick_available_font()
        self.log_text = tk.Text(log_frame, height=15, wrap=tk.WORD, font=(font, 11))
        scrollbar = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))

        self.status_var = tk.StringVar(value="就绪")
        status_bar = ttk.Label(main_frame, textvariable=self.status_var, relief=tk.SUNKEN)
        status_bar.grid(row=8, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(10, 0))

        footer_frame = ttk.Frame(main_frame)
        footer_frame.grid(row=9, column=0, columnspan=3, pady=(10, 5), sticky=(tk.W, tk.E))
        footer_frame.columnconfigure((0, 1, 2), weight=1)
        ttk.Label(footer_frame, text="作者: 王一健").grid(row=0, column=0, sticky=tk.W)
        ttk.Label(footer_frame, text="邮箱：etn@live.com").grid(row=0, column=1, sticky=tk.EW)
        ttk.Label(footer_frame, text="翻译完需要打开CAD调整文字位置").grid(row=0, column=2, sticky=tk.E)

    def setup_changelog_tab(self):
        """设置版本更新日志标签页，内容读取自 changelog.json 文件"""
        import json

        changelog_main_frame = ttk.Frame(self.changelog_frame, padding="15")
        changelog_main_frame.pack(fill='both', expand=True)

        # 标题
        title_frame = ttk.Frame(changelog_main_frame)
        title_frame.pack(fill='x', pady=(0, 20))

        title_label = tk.Label(title_frame, text="CAD中法互译工具", 
                            font=('Microsoft YaHei', 18, 'bold'))
        title_label.pack()

        subtitle_label = tk.Label(title_frame, text="版本更新历史", 
                                font=('Microsoft YaHei', 12), fg='gray')
        subtitle_label.pack()

        # 创建滚动文本区域
        text_frame = ttk.Frame(changelog_main_frame)
        text_frame.pack(fill='both', expand=True)
        text_frame.columnconfigure(0, weight=1)
        text_frame.rowconfigure(0, weight=1)

        # 文本框和滚动条
        self.changelog_text = tk.Text(text_frame, wrap=tk.WORD, font=('Consolas', 10), 
                                    bg='#f8f9fa', fg='#333333', padx=15, pady=15)
        changelog_scrollbar = ttk.Scrollbar(text_frame, orient=tk.VERTICAL, command=self.changelog_text.yview)
        self.changelog_text.configure(yscrollcommand=changelog_scrollbar.set)

        self.changelog_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        changelog_scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))

        # 尝试从外部 JSON 文件加载 changelog 内容
        changelog_path = os.path.join(os.getcwd(), "changelog.json")
        try:
            with open(changelog_path, 'r', encoding='utf-8') as f:
                changelog_data = json.load(f)

            content_lines = []
            for entry in changelog_data.get("changelog", []):
                version = entry.get("version", "未知版本")
                date = entry.get("date", "")
                title = entry.get("title", "")
                content_lines.append(f"版本 {version} - {date} {title}".strip())
                content_lines.append("=" * 80)
                content_lines.extend(entry.get("content", []))
                content_lines.append("")  # 空行分隔

            final_text = '\n'.join(content_lines).strip()
            self.changelog_text.insert('1.0', self.safe_text_for_tkinter(final_text))
            self.changelog_text.config(state='disabled')
        except Exception as e:
            self.changelog_text.insert('1.0', f"无法加载更新日志文件: {e}")

        # 底部信息
        bottom_frame = ttk.Frame(changelog_main_frame)
        bottom_frame.pack(fill='x', pady=(15, 0))

        info_label = tk.Label(bottom_frame, 
                            text="© 2025 Honsen非洲 - CAD中法互译工具 v2.2 | 编码问题修复版", 
                            font=('Microsoft YaHei', 9), fg='gray')
        info_label.pack()
    def browse_input_file(self):
        filename = filedialog.askopenfilename(
            title="选择DXF文件",
            filetypes=[("DXF files", "*.dxf"), ("All files", "*.*")]
        )
        if filename:
            self.input_file.set(filename)

            # 自动设置输出目录为输入文件所在目录
            if not self.output_dir.get():
                self.output_dir.set(os.path.dirname(filename))

            # 自动根据选择的文件名和翻译模式设置输出名
            base_name = os.path.splitext(os.path.basename(filename))[0]
            now = datetime.now()
            timestamp = now.strftime('%Hh%M_%d-%m-%y')
            
            # 根据翻译模式设置前缀
            if self.translation_mode.get() == 'zh_to_fr':
                prefix = 'fr'
            else:
                prefix = 'zh'
            
            self.output_name.set(f"{prefix}_{base_name}_{timestamp}")
    
    def browse_output_dir(self):
        directory = filedialog.askdirectory(title="选择输出目录")
        if directory:
            self.output_dir.set(directory)
    def safe_log(self, message):
        """安全日志记录（防止 surrogate 字符或日志回调死循环）"""
        if not self.log_callback:
            print("[无日志回调]:", message)
            return

        try:
            cleaned = self.cleaner.full_clean(str(message))
            self.log_callback(cleaned)
        except Exception as e:
            print("[日志记录失败]", e)
            print("原始日志内容:", repr(message))

    def log_message(self, message, level="INFO"):
        try:
            if hasattr(self, 'translator') and hasattr(self.translator, 'cleaner'):
                cleaned = self.translator.cleaner.clean_for_log(message)
            else:
                cleaned = str(message)
            safe_message = self.safe_text_for_tkinter(cleaned)
            if self.log_text and self.log_text.winfo_exists():
                self.log_text.insert(tk.END, safe_message + '\n')
                self.log_text.see(tk.END)
        except Exception as e:
            print("[日志处理异常]:", e)
            print("原始内容:", repr(message))
    def on_close(self):
        """窗口关闭时安全退出"""
        self.root.quit()
        self.root.destroy()

    def check_log_queue(self):
        """检查日志队列并更新UI（含异常处理）"""
        try:
            while True:
                message = self.log_queue.get_nowait()
                if isinstance(message, str):  # 防御式检查
                    # 使用安全文本处理
                    safe_message = self.safe_text_for_tkinter(message)
                    self.log_text.insert(tk.END, safe_message + "\n")
                    self.log_text.see(tk.END)
        except queue.Empty:
            pass
        except Exception as e:
            import traceback
            print("日志处理异常:")
            traceback.print_exc()
        finally:
            if hasattr(self, 'root') and self.root.winfo_exists():
                self.root.after(100, self.check_log_queue)

    def clear_log(self):
        """清除日志内容"""
        self.log_text.delete(1.0, tk.END)
    
    def validate_inputs(self):
        if not self.input_file.get():
            messagebox.showerror("错误", "请选择输入文件")
            return False
        
        if not os.path.exists(self.input_file.get()):
            messagebox.showerror("错误", "输入文件不存在")
            return False
        
        if not self.input_file.get().lower().endswith('.dxf'):
            messagebox.showerror("错误", "请选择DXF文件")
            return False
        
        if not self.output_dir.get():
            messagebox.showerror("错误", "请选择输出目录")
            return False
        
        if not os.path.exists(self.output_dir.get()):
            messagebox.showerror("错误", "输出目录不存在")
            return False
        
        if not self.output_name.get().strip():
            messagebox.showerror("错误", "请输入输出文件名")
            return False
        
        return True

    # 加载和保存 API Key
    def load_api_keys(self):
        """从本地配置文件加载 API Key"""
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    self.deepl_key.set(config.get("deepl_key", ""))
                    self.chatgpt_key.set(config.get("chatgpt_key", ""))
                    self.log_message(" 已加载保存的 API Key")
            except Exception as e:
                self.log_message(f" 加载配置失败: {e}")

    def save_api_keys(self):
        """保存 API Key 到本地配置文件"""
        try:
            config = {
                "deepl_key": self.deepl_key.get().strip(),
                "chatgpt_key": self.chatgpt_key.get().strip()
            }
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2)
            self.log_message(" API Key 已保存")
        except Exception as e:
            self.log_message(f" 保存配置失败: {e}")
    
    
    def start_translation(self):
        if not self.validate_inputs():
            return
        if not self.check_internet_connection():
            messagebox.showerror("网络错误", " 无法连接网络，请检查您的网络连接后重试。")
            self.log_message(" 网络中断，翻译终止")
            self.status_var.set("网络中断，已取消")
            self.progress.stop()
            self.start_button.config(state='normal')
            return
        translator = CADChineseTranslator(log_callback=self.log_message)
        translator.use_engine = self.translation_engine.get().strip()

        # 设置用户输入的 API Key
        translator.deepl_api_key = self.deepl_key.get().strip()
        translator.chatgpt_api_key = self.chatgpt_key.get().strip()
        if translator.deepl_api_key:
            import deepl
            try:
                translator.deepl_translator = deepl.Translator(translator.deepl_api_key)
                self.log_message(" DeepL 引擎初始化成功")
            except Exception as e:
                self.log_message(f" DeepL 初始化失败: {e}")
                messagebox.showerror("错误", "翻译失败: 未正确配置 DeepL API Key 或初始化失败")
                return
        # 主线程中创建翻译器并传入线程
        self.translator = self._create_translator()
        # 禁用开始按钮
        self.start_button.config(state='disabled')
        self.progress.start()
        self.status_var.set("翻译中...")
        
        # 构建输出文件路径
        output_file = os.path.join(
            self.output_dir.get(), 
            self.output_name.get().strip() + '.dxf'
        )
        
        # 在新线程中执行翻译
        def translation_thread():
            try:
                translator.translate_cad_file(
                    self.input_file.get(),
                    output_file,
                    self.translation_mode.get(),
                    self.translate_blocks.get()
                )
                self.root.after(0, self.translation_complete, True, "翻译完成！")
            except Exception as e:
                import traceback
                err = traceback.format_exc()
                error_msg = f"翻译失败: {translator.cleaner.safe_utf8(err)}"
                self.log_message(error_msg)
                self.root.after(0, self.translation_complete, False, error_msg)

        thread = threading.Thread(target=translation_thread, daemon=True)
        thread.start()
    
    def translation_complete(self, success, message):
        self.progress.stop()
        self.start_button.config(state='normal')
        
        if success:
            self.status_var.set("完成")
            messagebox.showinfo("成功", message)
            self.log_message("=" * 50)
        else:
            self.status_var.set("失败")
            safe = self.safe_text_for_tkinter(str(message))
            messagebox.showerror("错误", safe)
            self.log_message(f"ERROR: {safe}")

    def check_internet_connection(self, url='http://www.google.com', timeout=3):
        try:
            urllib.request.urlopen(url, timeout=timeout)
            return True
        except Exception:
            return False

    def run(self):
        self.root.mainloop()


def main():
    app = CADTranslatorGUI()
    app.run()


if __name__ == '__main__':
    main()