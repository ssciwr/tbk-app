FROM node:22-slim AS build

WORKDIR /app
COPY frontend/package.json ./package.json
RUN npm install
COPY frontend ./
RUN npm run build

FROM node:22-slim
WORKDIR /app
COPY --from=build /app/build ./build
COPY --from=build /app/package.json ./package.json
RUN npm install --omit=dev

EXPOSE 3000
CMD ["node", "build"]
