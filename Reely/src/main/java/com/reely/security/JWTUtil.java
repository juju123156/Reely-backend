package com.reely.security;

import com.reely.exception.CustomException;
import com.reely.exception.ErrorCode;
import io.jsonwebtoken.ExpiredJwtException;
import io.jsonwebtoken.JwtException;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.SignatureException;
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

        try {
            return (!this.isExpired(token)) && type.equals(this.getType(token));  // 만료되지 않은 경우 유형 비교
        } catch (ExpiredJwtException e) {
            log.info("만료된 토큰", e);
            return false;
        } catch (SignatureException e) {
            log.info("서명 불일치", e);
            return false; // 서명이 일치하지 않음
        } catch (JwtException e) {
            log.info("잘못된 토큰", e);
            return false;
        } catch (Exception e) {
            log.info("기타 예외", e);
            return false;
        }
    };

}
