import { useEffect, useState } from "react";
import { getHealth } from "./api.js";

function App() {
  const [health, setHealth] = useState({
    label: "检查中",
    detail: "正在请求后端 /health",
  });

  useEffect(() => {
    let cancelled = false;

    getHealth()
      .then((response) => {
        if (cancelled) {
          return;
        }
        const status = response.data?.data?.status;
        const requestId = response.data?.request_id;
        if (response.status === 200 && status === "ok") {
          setHealth({
            label: "正常",
            detail: requestId
              ? `后端健康检查通过，request_id：${requestId}`
              : "后端健康检查通过",
          });
          return;
        }
        setHealth({
          label: "异常",
          detail: "健康检查返回了非预期内容",
        });
      })
      .catch(() => {
        if (cancelled) {
          return;
        }
        setHealth({
          label: "无法连接",
          detail: "打不开后端。请先启动 http://localhost:8003 ，并确认 CORS 已放行当前页面地址。",
        });
      });

    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main className="page">
      <section className="card">
        <p className="eyebrow">第一版骨架</p>
        <h1>语音约碰面地点</h1>
        <p className="lead">
          后续将支持按住说话，为同一座城市的两个人推荐中间附近的店铺。本轮只验证页面能打开，以及后端健康检查。
        </p>
        <dl className="status">
          <div>
            <dt>后端状态</dt>
            <dd data-state={health.label}>{health.label}</dd>
          </div>
          <p>{health.detail}</p>
        </dl>
      </section>
    </main>
  );
}

export default App;
