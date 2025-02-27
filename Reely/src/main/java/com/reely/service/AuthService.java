package com.reely.service;

public interface AuthService {
    Boolean isExistRefreshToken(String username);

    void saveRefreshToken(String username, String refreshToken, Long ExpiredMs);

    void deleteRefreshToken(String username);
}
