"""业务路由汇总：所有模块共用一套资源路由，由领域服务完成分派。"""
from __future__ import annotations

from app.routers import resource, substitution

# substitution 是带固定前缀的多段路由，先注册可避免被通用 /api/{module} 抢占
ROUTERS = [substitution, resource]
