package com.reely.controller;

import com.reely.dto.TokenDto;
import com.reely.exception.CustomException;
import com.reely.exception.ErrorCode;
import com.reely.security.JWTUtil;
import com.reely.security.TokenConstants;
import com.reely.service.AuthService;
import jakarta.servlet.http.Cookie;

import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Controller;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;



@Controller
@Slf4j
@RequestMapping("/api/auth")
public class AuthController {
    private final JWTUtil jwtUtil;

    private final AuthService authService;

    public AuthController(JWTUtil jwtUtil, AuthService authService) {
        this.jwtUtil = jwtUtil;
        this.authService = authService;
    }

    @PostMapping("/reissue")
    public ResponseEntity<?> reissue(@RequestBody TokenDto resTokenDto) {
        //get refresh token
        String refresh = resTokenDto.getRefreshToken();

        // 토큰 유효성 체크
        if (!jwtUtil.isValid(refresh, TokenConstants.TOKEN_TYPE_REFRESH)) {
            log.info("[ERROR] refresh token is not valid");
            throw new CustomException(ErrorCode.UNAUTHORIZED);
        }

        String username = jwtUtil.getUsername(refresh);
        String role = jwtUtil.getRole(refresh);

        // refresh 토큰이 db에 존재하는지 확인
        if (!authService.isExistRefreshToken(username)) {
            log.info("[ERROR] refresh token is not exist");
            throw new CustomException(ErrorCode.UNAUTHORIZED);
        }

        // 토큰 발급
        String newAccess = jwtUtil.createJwt(TokenConstants.TOKEN_TYPE_ACCESS, username, role, TokenConstants.ACCESS_TOKEN_EXPIRATION);
        String newRefresh = jwtUtil.createJwt(TokenConstants.TOKEN_TYPE_REFRESH, username, role, TokenConstants.REFRESH_TOKEN_EXPIRATION);
        
        // 기존 refresh 삭제 처리
        authService.deleteRefreshToken(username);

        // refresh > redis 저장
        authService.saveRefreshToken(username, newRefresh, TokenConstants.REFRESH_TOKEN_EXPIRATION);

        TokenDto tokenDto = TokenDto.builder()
                .accessToken(newAccess)
                .refreshToken(newRefresh)
                .build();

        return new ResponseEntity<>(tokenDto, HttpStatus.OK);
    }

    //@PostMapping("/logout")
    private Cookie createCookie(String key, String value) {

        Cookie cookie = new Cookie(key, value);
        cookie.setMaxAge(24*60*60);
        //cookie.setSecure(true);
        //cookie.setPath("/");
        cookie.setHttpOnly(true);

        return cookie;
    }
}
