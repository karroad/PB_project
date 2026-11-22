from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", extra="ignore")

    APP_NAME: str = "SiteForge AI"
    DATA_DIR: Path = BASE_DIR / "data"
    DATABASE_URL: str = ""
    PUBLIC_BASE_URL: str = "http://localhost:8000"
    FRONTEND_ORIGIN: str = "http://localhost:3000"

    SECRET_KEY: str = "change-me-to-a-long-random-string"
    ENCRYPTION_KEY: str = ""
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 720
    ADMIN_EMAIL: str = "admin@siteforge.local"
    ADMIN_PASSWORD: str = "admin123"

    AI_PROVIDER: str = "auto"  # auto | anthropic | claude_cli | offline
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL: str = "claude-opus-5-5"
    ANTHROPIC_EFFORT: str = "medium"
    # claude_cli: run content on the monthly Claude subscription via the Claude Code CLI
    # (the machine must have `claude` installed and be logged in with that account, e.g. server 65/116).
    CLAUDE_CLI_BIN: str = "claude"
    CLAUDE_CLI_MODEL: str = ""        # empty -> the CLI/subscription default model
    CLAUDE_CLI_TIMEOUT: int = 240

    FAL_KEY: str = ""
    FAL_MODEL: str = "fal-ai/flux/schnell"

    # Code generation: the AI that writes each site's unique HTML/CSS/JS (separate from the content AI above).
    #   auto -> z.ai when ZAI_API_KEY is set, else the deterministic template renderer (offline).
    AI_CODE_GENERATION: bool = True          # False -> always use the built-in template renderer
    CODE_PROVIDER: str = "auto"              # auto | zai | offline
    ZAI_API_KEY: str = ""                    # z.ai GLM Coding Plan key (writes the code)
    ZAI_BASE_URL: str = "https://api.z.ai/api/anthropic"   # Anthropic-compatible endpoint used by the coding plan
    ZAI_MODEL: str = "glm-5.3-flash"         # client: use Flash only (the full model is ~4x the price)
    CODE_MAX_TOKENS: int = 32000
    CODE_TIMEOUT_SECONDS: int = 180

    MAX_CONCURRENT_JOBS: int = 3
    AI_MAX_CONCURRENT_REQUESTS: int = 4
    STEP_RETRIES: int = 2
    SIMULATED_STEP_DELAY: float = 0.45

    # Scaling: set REDIS_URL to share the job queue + event bus between API replicas
    # and any number of `python -m app.worker` processes.
    REDIS_URL: str = ""
    RUN_EMBEDDED_WORKER: bool = True  # API process also executes jobs (disable when running dedicated workers)
    JOB_TIMEOUT_SECONDS: int = 1800
    STEP_TIMEOUT_SECONDS: int = 600

    NOTIFY_WEBHOOK_URL: str = ""  # optional Slack/Teams/Discord-compatible webhook for notifications

    RUN_MONITOR: bool = True
    MONITOR_INTERVAL_SECONDS: int = 60
    STALE_JOB_SECONDS: int = 300  # running jobs without heartbeat for this long are resumed
    PROVIDER_CONCURRENCY: int = 2  # concurrent infra/deploy operations per hosting provider
    SERVER_PUBLIC_IP: str = ""  # public IP of the server hosting sites, used for DNS A records

    # Automation policy (client decision: sites go online automatically, domains are bought via API)
    AUTO_PUBLISH: bool = True  # publish without a human sign-off
    APPROVAL_DOMAIN_PURCHASE: bool = True  # an admin confirms each paid domain purchase
    APPROVAL_DNS_CHANGES: bool = False
    APPROVAL_PROVISION_HOSTING: bool = True  # paid servers (e.g. Hetzner)
    DOMAIN_MAX_PRICE: float = 50.0  # hard cap per domain registration (provider currency); 0 disables buying
    DOMAIN_REGISTRATION_YEARS: int = 1
    DOMAIN_AUTO_RENEW: bool = True
    DOMAIN_ACTIVATION_TIMEOUT_SECONDS: int = 420  # how long the infrastructure step waits for a new domain to activate
    # Simulate Cloudflare/OVH (no real API calls, no charges) — for demos and testing only
    SANDBOX_PROVIDERS: bool = False
    DOCKER_ENABLED: bool = False
    BUILD_NEXTJS: bool = False

    @property
    def database_url(self) -> str:
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return f"sqlite:///{(self.DATA_DIR / 'siteforge.db').as_posix()}"

    @property
    def sites_dir(self) -> Path:
        return self.DATA_DIR / "sites"

    @property
    def deployments_dir(self) -> Path:
        return self.DATA_DIR / "deployments"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    for d in (s.DATA_DIR, s.sites_dir, s.deployments_dir):
        d.mkdir(parents=True, exist_ok=True)
    return s


settings = get_settings()
