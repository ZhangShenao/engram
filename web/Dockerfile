FROM node:22-slim

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

ENV GATEWAY_URL=http://gateway:18410
ENV NEXT_TELEMETRY_DISABLED=1

RUN npm run build

EXPOSE 18415
CMD ["npm", "start"]
