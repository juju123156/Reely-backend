FROM openjdk:17-jdk-slim   

CMD ["./backend/Reely/gradlew", "clean", "build"]

ARG JAR_FILE=build/libs/*.jar

COPY ${JAR_FILE} app.jar