module.exports = {
  apps: [
    {
      name: "shugu-backend",
      cwd: "/home/openclaw/shugu/backend",
      script: "/home/openclaw/shugu/backend/venv/bin/uvicorn",
      args: "shugu.app:app --host 127.0.0.1 --port 8701",
      interpreter: "none",
      autorestart: true,
      max_restarts: 10,
      min_uptime: "15s",
      restart_delay: 2000,
      env: {
        PYTHONUNBUFFERED: "1",
      },
    },
    {
      name: "shugu-frontend",
      cwd: "/home/openclaw/shugu/frontend",
      script: "npx",
      args: "next start -p 3100",
      interpreter: "none",
      autorestart: true,
      max_restarts: 10,
      min_uptime: "15s",
      restart_delay: 2000,
      env: {
        NODE_ENV: "production",
      },
    },
  ],
};
