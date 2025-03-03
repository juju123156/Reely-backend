package com.reely.serviceImpl;

import com.reely.service.AuthService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.stereotype.Service;

import java.util.concurrent.TimeUnit;

@Service
@Slf4j
public class AuthServiceImpl implements AuthService {

    @Autowired
    private RedisTemplate<String, String> redisTemplate;

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
}
