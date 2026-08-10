from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title='Northwind FNOL Backend')

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        'http://localhost:5173',
        'http://127.0.0.1:5173'
    ],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)


class ClaimMessage(BaseModel):
    message: str


@app.get('/health')
def health_check():
    return {'status': 'ok'}


@app.post('/api/claims/message')
def claim_message(data: ClaimMessage):
    return {
        'reply': 'I received your claim.',
        'received_message': data.message
    }
