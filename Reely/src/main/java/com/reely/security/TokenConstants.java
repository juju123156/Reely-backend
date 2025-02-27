package com.reely.security;

public class TokenConstants {
    private TokenConstants() {}

    public static final long ACCESS_TOKEN_EXPIRATION = 600000L;  // Access Token 만료 시간 (밀리초)
    public static final long REFRESH_TOKEN_EXPIRATION = 86400000L;  // Refresh Token 만료 시간 (밀리초)
    public static final String TOKEN_TYPE_ACCESS = "access";
    public static final String TOKEN_TYPE_REFRESH = "refresh";
    public static final String TOKEN_PREFIX = "Bearer ";  // Bearer Token Prefix
    public static final String AUTHORIZATION_HEADER = "Authorization";  // HTTP Authorization 헤더
    


}
