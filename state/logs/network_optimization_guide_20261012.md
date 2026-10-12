# Mac 网络速度优化指南

**问题**: Mac 访问 GitHub 慢，但其他设备正常  
**日期**: 2026-10-12

---

## 根本原因分析

### 1. DNS 未配置
```bash
$ networksetup -getdnsservers Wi-Fi
There aren't any DNS Servers set on Wi-Fi.
```
- **影响**: 域名解析依赖 DHCP 自动分配，可能很慢或不稳定
- **解决**: 手动配置快速 DNS

### 2. Clash 代理路由不当
- **问题**: GitHub 流量经过阿里云香港节点（`47.86.229.225`）
- **现状**: 只有一个代理节点，速度慢且不稳定
- **已修复**: 修改 `clash-verge.yaml`，让 GitHub 全部直连

### 3. git push 上传大量小文件
- **本次推送**: 1645 个对象，很多是小文件
- **特点**: 上传比下载慢得多，尤其是经过代理时

---

## 已完成的优化

### ✅ 修改 Clash 规则（已完成）

**文件**: `~/Library/Application Support/io.github.clash-verge-rev.clash-verge-rev/clash-verge.yaml`

**修改内容**:
```yaml
# 旧配置
- DOMAIN-SUFFIX,githubusercontent.com,DIRECT
- DOMAIN-SUFFIX,gh-proxy.com,DIRECT

# 新配置 - GitHub 全部直连
- DOMAIN-SUFFIX,github.com,DIRECT
- DOMAIN-SUFFIX,githubusercontent.com,DIRECT
- DOMAIN-SUFFIX,gh-proxy.com,DIRECT
- DOMAIN-SUFFIX,githubassets.com,DIRECT
- DOMAIN-KEYWORD,github,DIRECT
```

**生效方式**: 在 Clash Verge Rev 中点击"重载"按钮

---

## 待执行的优化

### 1. 配置 DNS（推荐）

打开终端执行：
```bash
# 使用 Cloudflare DNS（快速且隐私友好）
sudo networksetup -setdnsservers Wi-Fi 1.1.1.1 1.0.0.1

# 或使用 Google DNS
sudo networksetup -setdnsservers Wi-Fi 8.8.8.8 8.8.4.4

# 或使用国内阿里 DNS
sudo networksetup -setdnsservers Wi-Fi 223.5.5.5 223.6.6.6
```

验证：
```bash
networksetup -getdnsservers Wi-Fi
```

### 2. 重载 Clash 配置

1. 打开 Clash Verge Rev
2. 点击"重载"按钮（或按 Cmd+R）
3. 确认规则已更新

### 3. 清理当前推送进程

如果当前推送卡住，可以取消后重新推送：

```bash
# 杀死所有 git push 进程
pkill -f "git push"

# 重新推送（不使用代理）
cd ~/.agnes && unset http_proxy https_proxy && git push -u origin main
```

### 4. 临时关闭系统代理（仅对 git 操作）

```bash
# 方法 1: 在命令前加 env 清空代理
cd ~/.agnes && env -u http_proxy -u https_proxy git push -u origin main

# 方法 2: 配置 git 不使用系统代理
git config --global http.proxy ""
git config --global https.proxy ""
```

---

## 长期优化建议

### 1. 添加更多代理节点
- 当前只有一个阿里云香港节点
- 建议添加日本、美国等更快的节点
- 使用 url-test 自动选择最快节点

### 2. 使用 SSH 协议代替 HTTPS
```bash
# 切换远程为 SSH
cd ~/.agnes && git remote set-url origin git@github.com:xx13903033565-lang/agnes-config.git

# 配置 SSH key（如果还没有）
ssh-keygen -t ed25519 -C "xx13903033565-lang@users.noreply.github.com"
# 复制公钥到 GitHub Settings → SSH and GPG keys
```

SSH 优势：
- 不需要每次输入密码
- 不受系统代理影响
- 连接更稳定

### 3. 优化 Clash 配置
```yaml
# 启用 TCP 并发
tcp-concurrent: true  # 已启用

# 调整 keep-alive
keep-alive-interval: 1800  # 已设置

# 添加更多测速节点
- name: 自动选择
  type: url-test
  url: https://www.google.com/generate_204
  interval: 300
  tolerance: 50  # 降低容差，更快切换节点
  timeout: 5000  # 缩短超时时间
```

---

## 测试网络速度

### 测试直连速度
```bash
# 不使用代理测试 GitHub
curl -o /dev/null -s -w "%{time_total}\n" https://github.com

# 测试 API 速度
curl -o /dev/null -s -w "%{time_total}\n" https://api.github.com
```

### 测试代理速度
```bash
# 使用代理测试
http_proxy=http://127.0.0.1:7897 curl -o /dev/null -s -w "%{time_total}\n" https://github.com
```

### 对比结果
- 直连应该 < 1 秒
- 代理可能 > 3 秒（取决于节点质量）

---

## 当前推送状态

**进程数**: 3 个 git push 进程正在运行  
**建议**: 
1. 等待当前推送完成（可能还需要几分钟）
2. 如果超过 10 分钟未完成，取消后重新推送
3. 重新推送前先重载 Clash 配置

---

## 快速参考

### 查看当前代理配置
```bash
scutil --proxy
```

### 查看 Clash 是否运行
```bash
lsof -i :7897 | head -5
```

### 测试 DNS 解析速度
```bash
time dig github.com
```

### 查看网络连接
```bash
netstat -an | grep ESTABLISHED | grep github
```

---

**生成时间**: 2026-10-12 15:00  
**下次更新**: 添加新代理节点后
