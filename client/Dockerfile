# client/Dockerfile
# 构建阶段
FROM node:18-alpine AS build
WORKDIR /app
COPY package*.json ./
# 如果用 pnpm/yarn 自行替换
RUN npm ci
COPY . .
# 关键：指定 API 基地址给前端（让前端请求 /api 前缀）
ARG VITE_API_BASE=/api
ENV VITE_API_BASE=$VITE_API_BASE
RUN npm run build

# 运行阶段：Nginx 托管静态文件
FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
# 把我们自定义的 nginx 配置拷到镜像
COPY ./deploy/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]