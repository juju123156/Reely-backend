package com.reely.config;

import com.reely.security.CustomAuthenticationFailureHandler;
import com.reely.security.JWTFilter;
import com.reely.security.JWTUtil;
import com.reely.security.LoginFilter;
import com.reely.service.AuthService;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.authentication.AuthenticationManager;
import org.springframework.security.config.annotation.authentication.configuration.AuthenticationConfiguration;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;
import org.springframework.web.cors.CorsConfiguration;
import org.springframework.web.cors.CorsConfigurationSource;
import org.springframework.web.cors.UrlBasedCorsConfigurationSource;

import java.util.Arrays;

@Configuration
@EnableWebSecurity
public class SecurityConfig {
    private final AuthenticationConfiguration authenticationConfiguration;

    private final JWTUtil jwtUtil;

    private final CustomAuthenticationFailureHandler failureHandler;

    private final AuthService authService;

    public SecurityConfig(AuthenticationConfiguration authenticationConfiguration, JWTUtil jwtUtil, CustomAuthenticationFailureHandler failureHandler, AuthService authService) {
        this.authenticationConfiguration = authenticationConfiguration;
        this.jwtUtil = jwtUtil;
        this.failureHandler = failureHandler;
        this.authService = authService;
    }

    @Bean
    public AuthenticationManager authenticationManager(AuthenticationConfiguration configuration) throws Exception {

        return configuration.getAuthenticationManager();
    }

    @Bean
    public BCryptPasswordEncoder bCryptPasswordEncoder() {

        return new BCryptPasswordEncoder();
    }

    // 단일 CorsConfigurationSource 빈을 생성하여 전역 CORS 설정 적용
    @Bean
    public CorsConfigurationSource corsConfigurationSource() {
        CorsConfiguration configuration = new CorsConfiguration();
        // React 앱이나 기타 클라이언트의 주소를 명시
        configuration.setAllowedOrigins(Arrays.asList("http://localhost:3000","http://localhost:8081", "http://localhost:8080")); // 3000 테스트용
        // 명시적으로 허용할 HTTP 메서드 설정
        configuration.setAllowedMethods(Arrays.asList("GET", "POST", "PUT", "DELETE", "OPTIONS"));
        // 필요한 헤더를 명시 (추가 헤더 필요시 확장 가능)
        configuration.setAllowedHeaders(Arrays.asList("Authorization", "Content-Type"));
        // 클라이언트에 노출할 헤더 설정 (예: JWT 토큰이 담긴 헤더)
        configuration.setExposedHeaders(Arrays.asList("Authorization"));
        configuration.setAllowCredentials(true);
        configuration.setMaxAge(3600L);

        UrlBasedCorsConfigurationSource source = new UrlBasedCorsConfigurationSource();
        // 모든 엔드포인트에 대해 위 설정을 적용
        source.registerCorsConfiguration("/**", configuration);
        return source;
    }

    // @Bean
    // public SecurityFilterChain filterChain(HttpSecurity http) throws Exception {
    //     http.cors(cors -> cors.configurationSource(corsConfigurationSource()));
    //     http.csrf((auth) -> auth.disable());
    //     http.formLogin((auth) -> auth.disable());
    //     http.httpBasic((auth) -> auth.disable());
    //     http.authorizeHttpRequests((auth) -> auth
    //                     .requestMatchers("/api/auth/**").permitAll()
    //                     .requestMatchers("/api/member/join", "/api/member/duplicate-id").permitAll()
    //                     .requestMatchers("/api/**").permitAll()
    //                     .anyRequest().authenticated());

    //     http.addFilterBefore(new JWTFilter(jwtUtil), LoginFilter.class);
    //     http.addFilterAt(new LoginFilter(authenticationManager(authenticationConfiguration), this.jwtUtil, failureHandler, authService), UsernamePasswordAuthenticationFilter.class);
    //     http.sessionManagement((session) -> session
    //             .sessionCreationPolicy(SessionCreationPolicy.STATELESS));

    //     return http.build();
    // }

    @Bean
    public SecurityFilterChain filterChain(HttpSecurity http) throws Exception {
    http.cors(cors -> cors.configurationSource(corsConfigurationSource()));
    http.csrf((auth) -> auth.disable());
    http.formLogin((auth) -> auth.disable());
    http.httpBasic((auth) -> auth.disable());
    http.authorizeHttpRequests((auth) -> auth
                    .requestMatchers("/api/auth/**").permitAll()
                    .requestMatchers("/api/member/join", "/api/member/duplicate-id").permitAll()
                    .requestMatchers("/api/**").permitAll()
                    .anyRequest().authenticated());

    http.addFilterBefore(new JWTFilter(jwtUtil), LoginFilter.class);
    
    // LoginFilter를 특정 URL에만 적용
    LoginFilter loginFilter = new LoginFilter(authenticationManager(authenticationConfiguration), this.jwtUtil, failureHandler, authService);
    loginFilter.setFilterProcessesUrl("/api/auth/login"); // 로그인 URL 지정
    
    http.addFilterAt(loginFilter, UsernamePasswordAuthenticationFilter.class);
    
    http.sessionManagement((session) -> session
            .sessionCreationPolicy(SessionCreationPolicy.STATELESS));

    return http.build();
    }

}
