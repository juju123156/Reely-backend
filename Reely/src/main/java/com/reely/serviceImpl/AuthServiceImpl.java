package com.reely.serviceImpl;

import com.reely.service.AuthService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.concurrent.TimeUnit;

@Service
@Slf4j
@Transactional
public class AuthServiceImpl implements AuthService {

    private final RedisTemplate<String, String> redisTemplate;

    public AuthServiceImpl(RedisTemplate<String, String> redisTemplate) {
        this.redisTemplate = redisTemplate;
    }

    @Override
    public Boolean isExistRefreshToken(String username) {
        log.info("RefreshToken 체크");
        return redisTemplate.hasKey(username);
    }

    @Override
    public void saveRefreshToken(String username, String refreshToken, Long ExpiredMs) {
        log.info("RefreshToken 저장");
        redisTemplate.opsForValue().set(username, refreshToken, ExpiredMs, TimeUnit.SECONDS);
    }

    @Override
    public void deleteRefreshToken(String username) {
        redisTemplate.delete(username);
    }

    @Override
    public void saveEmailAuthCode(String email, String authType, long expiredSeconds) {
        log.info("이메일 인증코드 저장");
        redisTemplate.opsForValue().set(email, authType, expiredSeconds, TimeUnit.SECONDS);
    }

    @Override
    public String getEmailAuthCode(String email) {
        return redisTemplate.opsForValue().get(email);
    }

    @Override
    public void deleteEmailAuthCode(String email) {
        redisTemplate.delete(email);
    }
}
