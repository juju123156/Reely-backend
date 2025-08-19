package com.reely.service;

public interface AuthService {
    Boolean isExistRefreshToken(String username);

    void saveRefreshToken(String username, String refreshToken, Long ExpiredMs);

    void deleteRefreshToken(String username);

    void saveEmailAuthCode(String email, String authType, long expiredSeconds);

    String getEmailAuthCode(String email);

    void deleteEmailAuthCode(String email);
}
