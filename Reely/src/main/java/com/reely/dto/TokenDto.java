package com.reely.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.Setter;

@Getter
@Builder
public class TokenDto {
    private String accessToken;
    private String refreshToken;
}
