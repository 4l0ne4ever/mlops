# Live Demo (Target App that, khong mock)

## 0) Bring-up mot lan
```bash
bash scripts/aws/run-ephemeral-ui-test.sh --key-path ~/.ssh/agentops-key.pem
```

Lay `EC2_IP` moi tu output script.

## 1) Xac nhan service that (SSH vao EC2)
```bash
export EC2_IP=<EC2_IP_MOI>
ssh -i ~/.ssh/agentops-key.pem -o StrictHostKeyChecking=no "ubuntu@$EC2_IP"
```

Trong EC2:
```bash
sudo systemctl status agentops-target-prod agentops-target-staging agentops-orchestrator agentops-dashboard --no-pager
curl -s -o /dev/null -w "prod:%{http_code}\n" http://127.0.0.1:9000/health
curl -s -o /dev/null -w "staging:%{http_code}\n" http://127.0.0.1:9001/health
curl -s -o /dev/null -w "orch:%{http_code}\n" http://127.0.0.1:7000/health
curl -s -o /dev/null -w "ui:%{http_code}\n" http://127.0.0.1/
```

Ky vong: tat ca `200`.

## 2) Goi Target App truc tiep (real inference)
Tu local hoac trong EC2:
```bash
curl -X POST "http://$EC2_IP:9001/translate" \
  -H "Content-Type: application/json" \
  -d '{"text":"Xin chao, day la demo that","source_lang":"vi","target_lang":"en"}'
```

Day la output that tu target app, khong phai mock.

## 3) Trigger pipeline that
```bash
curl -X POST "http://$EC2_IP:7000/trigger" \
  -H "Content-Type: application/json" \
  -d '{"trigger_type":"manual"}'
```

Lay `run_id` tu response.

## 4) Demo tren UI that
Mo:
```bash
open "http://$EC2_IP/"
```

Demo theo thu tu:
- Overview
- Pipeline Runs (tim `run_id` vua tao)
- Run Detail (quality score + breakdown + decision)
- Version History / Comparison

## 5) Neu UI loi
Trong EC2:
```bash
sudo journalctl -u agentops-dashboard -n 80 --no-pager
sudo journalctl -u nginx -n 80 --no-pager
```

## 6) Sau demo
```bash
bash scripts/aws/terminate-and-clean.sh
```
