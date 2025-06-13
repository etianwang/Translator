import re
import unicodedata

class TextCleaner:
    def __init__(self):
        self.french_char_pattern = re.compile(r'[éèêàçôùûîÉÈÊÀÇÔÙÛÎ]', re.IGNORECASE)
        self.emoji_pattern = re.compile(
            "["
            u"\U0001F600-\U0001F64F"
            u"\U0001F300-\U0001F5FF"
            u"\U0001F680-\U0001F6FF"
            u"\U0001F1E0-\U0001F1FF"
            u"\U00002702-\U000027B0"
            u"\U000024C2-\U0001F251"
            "]+", flags=re.UNICODE
        )

    def remove_surrogates(self, text):
        return ''.join(c for c in text if not (0xD800 <= ord(c) <= 0xDFFF))

    def remove_invalid_unicode(self, text):
        result = []
        for c in text:
            if self.is_valid_char(c):
                result.append(c)
        return ''.join(result)


    def is_valid_char(self, char):
        try:
            code = ord(char)
            if 0xD800 <= code <= 0xDFFF:
                return False  # surrogate pair
            if code == 0xFFFD:
                return False  # replacement char
            if self.is_chinese(char):
                return True
            # 保留拉丁字母（包括重音符号），覆盖 Latin-1 Supplement & Latin Extended-A
            if 0x00A0 <= code <= 0x017F:
                return True
            if unicodedata.category(char).startswith('L'):  # 所有可打印的字母
                return True
            return char.isprintable()
        except:
            return False

    def is_chinese(self, c):
        code = ord(c)
        return (
            0x4E00 <= code <= 0x9FFF or
            0x3400 <= code <= 0x4DBF or
            0x20000 <= code <= 0x2A6DF
        )

    def clean_format_control(self, text):
        # 清除 CAD 样式控制符（如 \f宋体;），不动任何花括号和中文结构
        text = re.sub(r'\\[fFcCpPhHwWqQaA][^;]*;', '', text)
        text = re.sub(r'\\[nNtT]', ' ', text)
        text = re.sub(r'\\\\', r'\\', text)
        return re.sub(r'\s+', ' ', text).strip()
    
    def fix_brace_pairing(self, text):
        """自动闭合单边花括号 {xxx → {xxx} 或 xxx} → {xxx}"""
        if text.count('{') > text.count('}'):
            text += '}'
        elif text.count('}') > text.count('{'):
            text = '{' + text
        return text
    
    def normalize_french_punctuation(self, text):
        """规范化法语引号 <<...>> → «...»"""
        text = re.sub(r'<<\s*', '« ', text)
        text = re.sub(r'\s*>>', ' »', text)
        return text



    def remove_emoji(self, text):
        # 更安全：逐字符判断 emoji，而不是整段正则（避免误杀中文）
        def is_emoji(char):
            cp = ord(char)
            return (
                0x1F600 <= cp <= 0x1F64F or
                0x1F300 <= cp <= 0x1F5FF or
                0x1F680 <= cp <= 0x1F6FF or
                0x1F1E0 <= cp <= 0x1F1FF or
                0x2600  <= cp <= 0x26FF or     # ☀☁
                0x2700  <= cp <= 0x27BF or     # ✂✈
                0xFE00  <= cp <= 0xFE0F or     # emoji variant selectors
                0x1F900 <= cp <= 0x1F9FF or
                0x1F018 <= cp <= 0x1F270 or
                0x238C <= cp <= 0x2454 or
                cp in (0x3030, 0x00A9, 0x00AE, 0x303D, 0x2049, 0x203C)
            )
        return ''.join(c for c in text if not is_emoji(c))

    def safe_utf8(self, text):
        try:
            return text.encode('utf-8', 'ignore').decode('utf-8')
        except:
            return ''

    def fix_common_encoding_errors(self, text):
        fixes = {
            'Ã©': 'é', 'Ã¨': 'è', 'Ã ': 'à', 'Ã§': 'ç', 'Ã´': 'ô',
            'Ãª': 'ê', 'Ã®': 'î', 'Ã¹': 'ù', 'Ã»': 'û', 'Ã‰': 'É',
            'â€“': '–', 'â€”': '—', 'â€˜': '‘', 'â€™': '’', 'â€œ': '“', 'â€': '”',
        }
        for wrong, correct in fixes.items():
            text = text.replace(wrong, correct)
        return text
    
    def full_clean(self, text, debug=False, log_func=None):
        if not text:
            return '' 
        original = str(text)
        if not original.strip():
            return ''
        # 记录清洗日志
        logs = []

        text = unicodedata.normalize('NFC', original)
        if debug and text != original:
            logs.append("[NFC归一化] 内容发生变化")

        fixed = self.fix_common_encoding_errors(text)
        if debug and fixed != text:
            logs.append("[编码修复] 替换了乱码字符")
        text = fixed

        fmt_cleaned = self.clean_format_control(text)
        if debug and fmt_cleaned != text:
            logs.append("[格式控制] 移除了 CAD 控制符")
        text = fmt_cleaned

        emoji_removed = self.remove_emoji(text)
        if debug and emoji_removed != text:
            logs.append("[Emoji清除] 去除表情符号")
        text = emoji_removed

        unicode_cleaned = self.remove_invalid_unicode(text)
        if debug and unicode_cleaned != text:
            logs.append("[非法Unicode] 清除不合法字符")
        text = unicode_cleaned

        surrogate_cleaned = self.remove_surrogates(text)
        if debug and surrogate_cleaned != text:
            logs.append("[代理字符清理] 移除 surrogate pair")
        text = surrogate_cleaned

        safe = self.safe_utf8(text)
        if debug and safe != text:
            logs.append("[UTF-8修复] 重新编码清理")
        text = safe.strip()
        text = self.normalize_french_punctuation(text)
        text = self.fix_brace_pairing(text)
        if debug and log_func and text != original:
            log_func("=" * 30 + " 清洗日志 " + "=" * 30)
            log_func(f"清洗前: {repr(original)}")
            log_func(f"清洗后: {repr(text)}")
            for line in logs:
                log_func(" - " + line)
            log_func("=" * 75)

        return text



    def clean_for_log(self, text):
        if not text:
            return ''
        return self.remove_emoji(self.remove_surrogates(str(text)))
