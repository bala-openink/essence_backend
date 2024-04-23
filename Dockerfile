# For more information, please refer to https://aka.ms/vscode-docker-python
FROM public.ecr.aws/lambda/python:3.12

# Warning: A port below 1024 has been exposed. This requires the image to run as a root user which is not a best practice.
# For more information, please refer to https://aka.ms/vscode-docker-python-user-rights`
EXPOSE 80

# Keeps Python from generating .pyc files in the container
ENV PYTHONDONTWRITEBYTECODE=1

# Turns off buffering for easier container logging
ENV PYTHONUNBUFFERED=1

# Environment variables for the app


# Copy the pyproject.toml and poetry.lock files (if present) into the container
COPY pyproject.toml poetry.lock* ${LAMBDA_TASK_ROOT}/

# Install Poetry
RUN pip install --no-cache-dir poetry

# Configure Poetry: Do not create a virtual env inside the Docker container
RUN poetry config virtualenvs.create false

# Install dependencies using Poetry
RUN poetry install --no-dev --no-interaction --no-ansi

COPY . ${LAMBDA_TASK_ROOT}/

# During debugging, this entry point will be overridden. For more information, please refer to https://aka.ms/vscode-docker-python-debug
CMD ["app.handler"]
