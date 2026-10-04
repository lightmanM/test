FROM cloakhq/cloakbrowser:latest

WORKDIR /service
ENV NODE_ENV=production \
    CLOAKBROWSER_AUTO_UPDATE=false \
    PORT=8000 \
    HOST=0.0.0.0

COPY package.json ./
RUN npm install --omit=dev && npx cloakbrowser install

COPY src ./src

EXPOSE 8000
CMD ["node", "src/server.mjs"]
