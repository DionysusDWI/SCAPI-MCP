from dataclasses import dataclass
from pathlib import Path
import json

@dataclass(frozen=True)
class Config:
    path: Path
    game_dir: Path
    runtime_dir: Path
    artifacts_dir: Path
    backups_dir: Path
    target: dict
    limits: dict
    timeout: float

    @classmethod
    def load(cls, path):
        path = Path(path).resolve()
        data = json.loads(path.read_text(encoding='utf-8'))
        def resolve(key):
            return (path.parent / data[key]).resolve()
        limits = data.get('limits', {})
        for key, maximum in [('max_region_cells', 4096), ('max_write_cells', 64)]:
            value = limits.get(key, maximum)
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError(f'{key} must be 1..{maximum}')
            limits[key] = value
        timeout = data.get('timeout_seconds', 15)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 120:
            raise ValueError('timeout_seconds must be > 0 and <= 120')
        return cls(path, resolve('game_dir'), resolve('runtime_dir'), resolve('artifacts_dir'),
                   resolve('backups_dir'), data['target'], limits, timeout)

    def host_settings(self):
        from .commands import descriptor
        target = dict(self.target)
        if target.get('backup'):
            target['backup_path'] = (self.path.parent / target['backup']).resolve().as_posix()
        return {'runtime': self.runtime_dir.as_posix(), 'backups': self.backups_dir.as_posix(),
                'artifacts': self.artifacts_dir.as_posix(), 'target': target,
                'limits': self.limits, 'version': '0.5.0', 'protocol': 3,'capabilities':descriptor()}
