package com.reely.dto;

import lombok.Getter;
import lombok.Setter;
import lombok.ToString;

@Getter
@Setter
@ToString
public class KmdbDto {
    private String docId;             // 문서ID
    private String pk;                // 기본키
    private String movieId;           // 등록ID
    private String movieSeq;          // 등록SEQ
    private String title;             // 영화명
    private String titleEng;          // 영문제명
    private String titleOrg;          // 원제명
    private String titleEtc;          // 기타제명
    private String directorNm;       // 감독명
    private String directorEnNm;     // 감독명(영문)
    private String directorId;       // 감독등록번호
    private String actorNm;          // 배우명
    private String actorEnNm;        // 배우명(영문)
    private String actorId;          // 배우등록번호
    private String nation;            // 제작국가
    private String company;           // 제작사
    private String prodYear;          // 제작년도
    private String plot;              // 줄거리
    private String runtime;           // 상영시간
    private String rating;            // 대표관람등급
    private String genre;             // 장르
    private String kmdbUrl;           // kmdb URL
    private String type;              // 유형구분
    private String use;               // 용도구분
    private String episodes;          // 영상 내 에피소드
    private String ratedYn;           // 심의여부
    private String repRatDate;        // 대표심의일
    private String repRlsDate;        // 대표개봉일
    private String ratingMain;        // 대표심의정보 여부
    private String ratingDate;        // 심의일
    private String ratingNo;          // 심의번호
    private String ratingGrade;       // 관람기준
    private String releaseDate;       // 개봉일자
    private String keywords;          // 키워드
    private String posterUrl;         // 포스터이미지URL
    private String stillUrl;          // 스틸이미지URL
    private String staffNm;           // 스텝이름
    private String staffRoleGroup;    // 스텝크레딧명
    private String staffRole;         // 스텝배역
    private String staffEtc;          // 스텝기타
    private String staffId;           // 스텝등록번호
    private String vodClass;          // VOD 구분
    private String vodUrl;            // VOD URL
    private String openThtr;          // 개봉극장
    private String screenArea;        // 관람지역
    private String screenCnt;         // 스크린수
    private String salesAcc;          // 누적매출액
    private String audiAcc;           // 누적관람인원
    private String statSource;        // 출처
    private String statDate;          // 기준일
    private String themeSong;         // 주제곡
    private String soundtrack;        // 삽입곡
    private String fLocation;         // 촬영장소
    private String awards1;           // 영화제수상내역
    private String awards2;           // 수상내역 기타
    private String regDate;           // 등록일
    private String modDate;           // 최종수정일
    private String codeNm;            // 외부코드명
    private String codeNo;            // 외부코드
    private String commCodes;         // 대표외부코드
}
