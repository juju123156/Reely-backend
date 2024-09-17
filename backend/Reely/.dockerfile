FROM openjdk:17-jdk-slim   

WORKDIR /app
COPY . .

CMD ["sh", "-c", "cd /app/backend/Reely && ./gradlew", "clean", "build"]

ARG JAR_FILE=build/libs/*.jar

COPY ${JAR_FILE} app.jar