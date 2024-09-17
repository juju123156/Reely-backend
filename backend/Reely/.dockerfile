FROM openjdk:17-jdk-slim   

WORKDIR /app

# 로컬의 JAR 파일을 Docker 이미지의 /app 디렉토리로 복사합니다.
COPY build/libs/*.jar app.jar

# JAR 파일을 실행할 명령어를 지정합니다.
ENTRYPOINT ["java", "-jar", "app.jar"]

# 컨테이너가 사용할 포트를 지정합니다. (스프링 부트의 기본 포트는 8080입니다)
EXPOSE 8080