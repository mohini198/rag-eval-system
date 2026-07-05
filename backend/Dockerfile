# Python 3.12 image use kar rahe hain
FROM python:3.12-slim

# Working directory set kar rahe hain
WORKDIR /code

# Requirements copy karke install kar rahe hain
COPY ./requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

# Pura backend code copy kar rahe hain
COPY . .

# Hugging Face ke liye permissions set kar rahe hain
RUN chmod -R 777 /code

# FastAPI ko port 7860 par run karne ki command (Hugging Face default port)
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "7860"]