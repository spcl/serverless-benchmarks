ARG BASE_IMAGE=node:18-slim
FROM ${BASE_IMAGE}

WORKDIR /app

# Copy package files first for better caching
COPY package*.json ./

# Install dependencies
RUN npm install --production

# Copy all application files
COPY . .

# Expose port 8080 for container communication
EXPOSE 8080

# Set environment variable for port
ENV PORT=8080

# Start the HTTP server
CMD ["node", "handler.js"]
