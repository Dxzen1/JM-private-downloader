# JM 私人下载站

一个适合手机使用的单用户下载门户：登录后输入漫画数字 ID，服务器在后台调用 `jmcomic` 下载，完成后生成 ZIP，并只向已登录用户提供下载。

> 使用者应确保已取得所需授权，并只在授权范围内使用；同时请遵守资源版权、内容分发规则和服务器所在地的法律要求。

## 脚本来源与致谢

本项目的下载能力通过 Python 依赖 [`jmcomic`](https://pypi.org/project/jmcomic/) 实现，其上游源码为 [hect0x7/JMComic-Crawler-Python](https://github.com/hect0x7/JMComic-Crawler-Python)，作者为 `hect0x7`，采用 MIT License。

本仓库没有冒充或声称隶属于 JM 官方，也不是官方 SDK。仓库中的 FastAPI 门户、登录、任务队列、ZIP 打包、Docker 与宝塔部署层是围绕上述依赖编写的独立集成代码；更完整的第三方说明见 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。

## 功能

- 单用户登录与安全会话 Cookie
- 漫画 ID 校验与重复任务抑制
- SQLite 持久化任务队列，服务重启后自动重新排队
- 后台串行下载，避免对上游造成突发压力
- 自动生成 ZIP，手机可直接下载
- 失败任务重试、手动删除、自动过期清理
- 存储空间配额
- CSRF 防护、安全响应头、下载路径校验
- `stub` 模拟模式，用于上线前测试

## 服务器要求

- 阿里云海外 ECS
- 宝塔面板
- Docker 与 Docker Compose
- 一个解析到服务器公网 IP 的域名
- 建议至少 2 核 CPU、2 GB 内存，并准备足够的数据盘空间

## 一、上传项目

把整个项目目录上传到服务器，例如：

```text
/www/wwwroot/jm-private-portal
```

在宝塔终端进入该目录：

```bash
cd /www/wwwroot/jm-private-portal
```

## 二、创建配置

复制环境变量模板：

```bash
cp .env.example .env
```

生成会话密钥：

```bash
openssl rand -hex 32
```

编辑 `.env`，至少替换：

```dotenv
ADMIN_USERNAME=你的登录用户名
ADMIN_PASSWORD=至少12位的独立强密码
SESSION_SECRET=刚生成的64位十六进制字符串
SECURE_COOKIE=true
JM_PROVIDER=jmcomic
MAX_STORAGE_GB=20
RETENTION_HOURS=168
```

`RETENTION_HOURS=168` 表示完成文件保留七天。过期任务和 ZIP 会自动删除。

## 三、配置授权参数

复制示例：

```bash
cp secrets/jm-option.example.yml secrets/jm-option.yml
```

编辑 `secrets/jm-option.yml`，按照你获得的官方授权填写账号、Token、允许的客户端实现和并发限制。不要修改或填写 `dir_rule.base_dir`，网站会为每个任务自动设置隔离目录。

配置文件会以只读方式挂载到容器内，不会通过网页返回。不要把 `.env` 或真实的 `jm-option.yml` 发给他人。

## 四、先用模拟模式验证

第一次上线建议在 `.env` 中设置：

```dotenv
JM_PROVIDER=stub
SECURE_COOKIE=false
```

启动：

```bash
docker compose up -d --build
```

在服务器本机检查：

```bash
curl http://127.0.0.1:18080/healthz
```

应该返回：

```json
{"status":"ok"}
```

## 五、在宝塔创建站点

1. 打开宝塔的“网站”，添加你的域名。
2. 申请并启用 Let's Encrypt SSL，开启“强制 HTTPS”。
3. 在站点的“配置文件”或“反向代理”中，把所有请求代理至 `http://127.0.0.1:18080`。
4. `deploy/baota-nginx.conf` 提供了可直接参考的 Nginx 配置。
5. 阿里云安全组只需公开 TCP `80` 和 `443`；不要公开 `18080`。

通过手机访问域名，登录后提交测试 ID。模拟任务会很快完成并出现“下载 ZIP”按钮。

## 六、启用 JM 下载组件

确认 HTTPS、登录、ZIP 下载和删除均正常后，将 `.env` 改为：

```dotenv
JM_PROVIDER=jmcomic
SECURE_COOKIE=true
```

重新创建容器：

```bash
docker compose up -d --build --force-recreate
```

查看运行日志：

```bash
docker compose logs -f --tail=100 portal
```

日志中不会主动打印网站登录密码，但上游组件可能输出请求信息，因此不要公开日志。

## 日常管理

查看状态：

```bash
docker compose ps
```

更新代码后重建：

```bash
docker compose up -d --build
```

停止：

```bash
docker compose down
```

备份以下目录：

```text
data/       SQLite 任务数据库
downloads/ 已生成的 ZIP
.env        网站配置和登录凭据
secrets/    JM 授权配置
```

## 安全建议

- 宝塔面板端口与 SSH 端口只允许你的固定 IP。
- 为宝塔开启两步验证，不要与网站共用密码。
- 不要将 `downloads` 配置为公开静态目录；应用会在登录校验后返回文件。
- 定期更新基础镜像与依赖，并检查服务器磁盘空间。
- 上游授权被撤销或发生异常时，立即把 `JM_PROVIDER` 改为 `stub` 并重启。
- 本项目设计为个人单用户、小并发服务，不应作为公开下载站。

## 本地测试

```bash
python -m venv .venv
```

```bash
. .venv/bin/activate
```

```bash
pip install -r requirements-dev.txt
```

```bash
pytest -q
```

## 常见问题

### 登录成功后又跳回登录页

如果尚未配置 HTTPS，临时设置 `SECURE_COOKIE=false`；正式上线并启用 HTTPS 后必须改回 `true`。

### 任务失败并提示找不到配置文件

确认 `secrets/jm-option.yml` 存在，且不是示例文件名。然后运行：

```bash
docker compose restart portal
```

### ZIP 很大，手机下载中断

确认宝塔/Nginx 未限制响应大小和超时时间。应用的文件响应支持现代浏览器下载；若未来需要分离存储，可将适配器扩展到对象存储。

### 为什么只能运行一个应用 worker

后台任务队列当前使用 SQLite 抢占与单消费者模式。保持 Uvicorn `--workers 1` 可避免同一服务器上出现多套清理循环；下载工作本身在后台线程中执行，不会阻塞页面访问。
