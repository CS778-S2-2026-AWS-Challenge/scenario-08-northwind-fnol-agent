from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title='Northwind FNOL Backend')


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
