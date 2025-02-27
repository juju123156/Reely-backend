package com.reely.security;

import com.reely.dto.MemberDto;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.util.ObjectUtils;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.io.PrintWriter;

import static com.reely.security.TokenConstants.*;

@Slf4j
public class JWTFilter extends OncePerRequestFilter {

    private final JWTUtil jwtUtil;

    public JWTFilter(JWTUtil jwtUtil) {

        this.jwtUtil = jwtUtil;
    }


    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain filterChain) throws ServletException, IOException {

        String authorization = request.getHeader(AUTHORIZATION_HEADER);

        // Authorization 헤더가 없거나 "Bearer "로 시작하지 않으면 넘어가기
        if (ObjectUtils.isEmpty(authorization) || !authorization.startsWith(TOKEN_PREFIX)) {
            filterChain.doFilter(request, response);
            return;
        }

        String accessToken = authorization.split(" ")[1];

        // 토큰 유효성 검사
        if (!jwtUtil.isValid(accessToken, TokenConstants.TOKEN_TYPE_ACCESS)) {
            sendErrorResponse(response, "Access token is not valid", HttpServletResponse.SC_UNAUTHORIZED);
            return;
        }


        // 토큰에서 사용자 정보 추출
        String username = jwtUtil.getUsername(accessToken);
        String role = jwtUtil.getRole(accessToken);

        MemberDto memberDto = new MemberDto();
        memberDto.setMemberPk(username);
        memberDto.setRole(role);

        // 사용자 인증 정보 설정
        CustomUserDetails customUserDetails = new CustomUserDetails(memberDto);
        Authentication authToken = new UsernamePasswordAuthenticationToken(customUserDetails, null, customUserDetails.getAuthorities());
        SecurityContextHolder.getContext().setAuthentication(authToken);

        filterChain.doFilter(request, response);
    }

    private void sendErrorResponse(HttpServletResponse response, String message, int statusCode) throws IOException {
        response.setStatus(statusCode);
        PrintWriter writer = response.getWriter();
        writer.print(message);
    }

}
