package com.reely.security;

import io.jsonwebtoken.ExpiredJwtException;
import io.jsonwebtoken.Jwts;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import javax.crypto.SecretKey;
import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;
import java.time.ZoneId;
import java.time.ZonedDateTime;
import java.util.Date;
@Slf4j
@Component
public class JWTUtil {
    private SecretKey secretKey;
    public JWTUtil(@Value("${spring.jwt.secret}") String secret) {
        this.secretKey = new SecretKeySpec(secret.getBytes(StandardCharsets.UTF_8), Jwts.SIG.HS256.key().build().getAlgorithm());
    }
    public String getUsername(String token) {
        return Jwts.parser()
                .verifyWith(secretKey)
                .build()
                .parseSignedClaims(token)
                .getPayload()
                .get("username", String.class);
    }

    public String getRole(String token) {
        return Jwts.parser()
                .verifyWith(secretKey)
                .build()
                .parseSignedClaims(token)
                .getPayload()
                .get("role", String.class);
    }

    private String getType(String token) {
        return Jwts.parser()
                .verifyWith(secretKey)
                .build()
                .parseSignedClaims(token)
                .getPayload()
                .get("type", String.class);
    }

    private Boolean isExpired(String token){
        return Jwts.parser()
                .verifyWith(secretKey)
                .build()
                .parseSignedClaims(token)
                .getPayload()
                .getExpiration()
                .before(Date.from(this.getDateTime().toInstant()));
    }


    public String createJwt(String type, String username, String role, Long expiredMs) {
        // 서울 시간대로 현재 시간 가져오기
        Date issuedAt = Date.from(this.getDateTime().toInstant());  // ZonedDateTime을 Date로 변환
        Date expiration = Date.from(this.getDateTime().plusMinutes(expiredMs).toInstant());  // 만료 시간 설정

        return Jwts.builder()
                .claim("type", type)
                .claim("username", username)
                .claim("role", role)
                .issuedAt(issuedAt)
                .expiration(expiration)
                .signWith(secretKey)
                .compact();
    }

    private ZonedDateTime getDateTime() {
        return ZonedDateTime.now(ZoneId.of("Asia/Seoul"));
    }

    public Boolean isValid(String token, String type){
        // null 체크
        if (token == null || type == null) {
            return false;
        }

        // 토큰 유형 검사
        if (!type.equals(this.getType(token))) {
            return  false;
        }

        // 토큰 만료 검사
        try {
            this.isExpired(token);
            return true;  // 만료되지 않음
        } catch (ExpiredJwtException e) {
            return false;  // 만료됨
        }

    };

}
