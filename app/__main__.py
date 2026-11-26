from app.main import create_app
from app.settings import load_settings
import uvicorn


if __name__ == "__main__":
    settings = load_settings()
    print(f"Operator: http://{settings.host}:{settings.port}/operator")
    print(f"Scoreboard: http://{settings.host}:{settings.port}/scoreboard")
    print(f"Operator key is stored at {settings.operator_key_path.resolve()} (or NEON_OPERATOR_KEY).")
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, workers=1)
