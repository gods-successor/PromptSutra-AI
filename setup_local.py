"""Configure a safe local .env without putting credentials into source control."""
from pathlib import Path
import secrets

root = Path(__file__).resolve().parent
path = root / '.env'
if path.exists():
    print('.env already exists; leaving it unchanged.')
else:
    example = (root/'.env.example').read_text(encoding='utf-8')
    example = example.replace('APP_SECRET=\n', f'APP_SECRET={secrets.token_urlsafe(48)}\n', 1)
    example = example.replace('DATABASE_URL=\n', f'DATABASE_URL=sqlite:///{(root / "promptsutra.db").as_posix()}\n', 1)
    path.write_text(example, encoding='utf-8')
    print('Created .env with a random secret. Add GEMINI_API_KEY when ready.')
