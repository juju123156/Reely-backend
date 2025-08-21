package com.reely.security;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.reely.dto.MemberDto;
import com.reely.dto.TokenDto;
import com.reely.service.AuthService;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.ServletInputStream;
import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.security.authentication.AuthenticationManager;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.AuthenticationException;
import org.springframework.security.core.GrantedAuthority;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;
import org.springframework.util.StreamUtils;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.Collection;
import java.util.Iterator;

import static com.reely.security.TokenConstants.*;

@Slf4j
public class LoginFilter extends UsernamePasswordAuthenticationFilter {
    private final AuthenticationManager authenticationManager;
    private final JWTUtil jwtUtil;

    private final AuthService authService;

    private  final CustomAuthenticationFailureHandler failureHandler;
    private final ObjectMapper objectMapper = new ObjectMapper();
    public LoginFilter(AuthenticationManager authenticationManager, JWTUtil jwtUtil, CustomAuthenticationFailureHandler failureHandler, AuthService authService) {
        this.authenticationManager = authenticationManager;
        this.jwtUtil = jwtUtil;
        this.failureHandler = failureHandler;
        this.authService =authService;
        this.setFilterProcessesUrl("/api/auth/login");
    }

    @Override
    public Authentication attemptAuthentication(HttpServletRequest request, HttpServletResponse response) throws AuthenticationException {

        log.info("================== loginFilter 시작 ===================");

        // JSON 형식으로 받은 데이터 파싱
        MemberDto memberDto  = new MemberDto();

        try {
            ServletInputStream inputStream = request.getInputStream();
            String messageBody = StreamUtils.copyToString(inputStream, StandardCharsets.UTF_8);
            memberDto = objectMapper.readValue(messageBody, MemberDto.class);

        } catch (IOException e) {
            throw new RuntimeException(e);
        }

        log.info("memberId={}", memberDto.getMemberId());
        log.info("memberPwd={}", memberDto.getMemberPwd());

        String memberId = memberDto.getMemberId();
        String memberPwd = memberDto.getMemberPwd();

        UsernamePasswordAuthenticationToken authToken = new UsernamePasswordAuthenticationToken(memberId, memberPwd, null);
        log.info("authToken={}", authToken);
        // AuthenticationManager를 사용하여 인증 진행
        return authenticationManager.authenticate(authToken);
    }

    @Override
    protected void successfulAuthentication(HttpServletRequest request, HttpServletResponse response, FilterChain chain, Authentication authentication) throws IOException {
        //유저 정보
        String username = authentication.getName();

        Collection<? extends GrantedAuthority> authorities = authentication.getAuthorities();
        Iterator<? extends GrantedAuthority> iterator = authorities.iterator();
        GrantedAuthority auth = iterator.next();
        String role = auth.getAuthority();

        // 토큰 생성
        String access = jwtUtil.createJwt(TokenConstants.TOKEN_TYPE_ACCESS, username, role, TokenConstants.ACCESS_TOKEN_EXPIRATION);
        String refresh = jwtUtil.createJwt(TokenConstants.TOKEN_TYPE_REFRESH, username, role, TokenConstants.REFRESH_TOKEN_EXPIRATION);

        // Refresh 토큰을 Redis에 저장
        authService.saveRefreshToken(username, refresh, TokenConstants.REFRESH_TOKEN_EXPIRATION);

        TokenDto tokenDto = TokenDto.builder()
                .accessToken(access)
                .refreshToken(refresh)
                .build();

        response.setContentType("application/json");
        response.setCharacterEncoding("UTF-8");
        ObjectMapper objectMapper = new ObjectMapper();
        response.getWriter().write(objectMapper.writeValueAsString(tokenDto));

        response.setStatus(HttpStatus.OK.value());
    }

    @Override
    protected void unsuccessfulAuthentication(HttpServletRequest request, HttpServletResponse response, AuthenticationException failed) throws IOException {
        log.info("token 발급 실패");
        failureHandler.onAuthenticationFailure(request, response, failed);
    }
}
