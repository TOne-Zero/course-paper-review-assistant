"""保存正式/模拟模式各自的评分配置，不覆盖内置预设。"""
import json
import os
import tempfile
from pathlib import Path

from paper_assistant.rubrics import parse_rubric_config, rubric_to_dict
from paper_assistant.schemas import AssistantError
from paper_assistant.rubric_defaults import weighted_rubric


class CriteriaStore:
    def __init__(self, directory, defaults):
        self.directory = Path(directory)
        self.defaults = defaults

    def load(self, mode):
        path = self.directory / f'{mode}.json'
        if not path.exists():
            return tuple(weighted_rubric(r) for r in self.defaults), self.defaults[0].id
        try:
            content = json.loads(path.read_text(encoding='utf-8'))
            if content['schema_version'] != '1.0':
                raise ValueError()
            rubrics = tuple(weighted_rubric(parse_rubric_config(data)) for data in content['rubrics'])
            if [r.id for r in rubrics] != [r.id for r in self.defaults] or content['active_id'] not in {r.id for r in rubrics}:
                raise ValueError()
            return rubrics, content['active_id']
        except (OSError, ValueError, KeyError, TypeError):
            raise AssistantError('已保存的评分配置无法读取，请核对rubrics/user_settings目录中的配置；未覆盖原文件。') from None

    def save(self, mode, rubrics, active_id):
        temporary = None
        try:
            content = json.dumps({'schema_version': '1.0', 'active_id': active_id,
                                  'rubrics': [rubric_to_dict(r) for r in rubrics]}, ensure_ascii=False, indent=2, allow_nan=False)
            self.directory.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.directory, suffix='.tmp', delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.directory / f'{mode}.json')
        except (OSError, ValueError):
            raise AssistantError('评分配置写入失败，请检查目录权限后重试；旧配置和评阅结果未更改。') from None
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
