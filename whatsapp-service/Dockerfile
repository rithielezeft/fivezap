# Dockerfile — WhatsApp Web service (Node + Puppeteer + Chromium)
FROM node:20-slim

WORKDIR /app/whatsapp-service

# Deps Chromium para whatsapp-web.js
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    libnss3 libatk-bridge2.0-0 libx11-xcb1 libxcomposite1 libxrandr2 \
    libxdamage1 libxfixes3 libxi6 libgbm1 libpangocairo-1.0-0 libasound2 \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

ENV PUPPETEER_SKIP_CHROMIUM_DOWNLOAD=true
ENV PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium
ENV CHROMIUM_PATH=/usr/bin/chromium

COPY whatsapp-service/package.json whatsapp-service/yarn.lock ./
RUN yarn install --ignore-engines --frozen-lockfile

COPY whatsapp-service/ ./

EXPOSE 3001
CMD ["node", "index.js"]
