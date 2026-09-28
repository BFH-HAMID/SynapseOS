.PHONY: install backend frontend seed dev docker docker-full audit test clean

install:            ## install backend + frontend dependencies
	cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/pip install -e . --no-deps
	cd frontend && npm install

backend:            ## run the API server (http://localhost:8000, docs at /docs)
	cd backend && .venv/bin/python -m synapseos.cli serve

frontend:           ## run the dashboard (http://localhost:3000)
	cd frontend && npm run dev

seed:               ## seed demo data (docs, 3 weeks of interactions + feedback)
	cd backend && .venv/bin/python -m synapseos.cli seed --reset

dev: backend frontend ## run both

docker:             ## lite stack (sqlite + embedded vector store)
	docker compose up --build

docker-full:        ## full stack (postgres + redis + qdrant)
	SYNAPSE_DB_URL=postgresql+psycopg2://synapse:synapse@postgres:5432/synapseos \
	SYNAPSE_REDIS_URL=redis://redis:6379/0 \
	SYNAPSE_VECTOR_BACKEND=qdrant \
	docker compose --profile full up --build

audit:              ## security audit against a running instance
	cd backend && .venv/bin/python -m synapseos.cli audit

clean:
	rm -rf backend/data backend/.venv frontend/node_modules frontend/.next
