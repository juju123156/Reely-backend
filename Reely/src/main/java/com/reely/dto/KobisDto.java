package com.reely.dto;

import lombok.Getter;
import lombok.Setter;
import lombok.ToString;

@Getter
@Setter
@ToString
public class KobisDto {

    private String movieCd; // 영화코드
    private String movieNm; // 영화명(국문)
    private String movieNmEn; // 영화명(영문)
    private String movieNmOg; // 영화명(원문)
    private String prdtYear; // 제작연도
    private String showTm; // 상영시간
    private String openDt; // 개봉연도
    private String prdtStatNm; // 제작상태명
    private String typeNm; // 영화유형명
    private String[] nations; // 제작국가
    private String nationNm; // 제작국가명
    private String[] genres; // 장르
    private String genreNm; // 장르명
    private String[] directors; // 감독
    private String peopleNm; // 감독명/배우명/스텝명
    private String peopleNmEn; // 감독명/배우명/스텝명(영문)
    private String[] actors; // 배우
    // private String peopleNm; // 배우명
    // private String peopleNmEn; // 배우명(영문)
    private String cast; // 배역명
    private String castEn; // 배역명(영문)
    private String showTypes; // 상영형태 구분
    private String showTypeGroupNm; // 상영형태 구분명
    private String showTypeNm; // 상영형태명
    private String[] audits; // 심의정보
    private String auditNo; // 심의번호
    private String watchGradeNm; // 관람등급 명칭
    private String[] companys; // 참여 영화사
    private String companyCd; // 참여 영화사 코드
    private String companyNm; // 참여 영화사명
    private String companyNmEn; // 참여 영화사명(영문)
    private String companyPartNm; // 참여 영화사 분야명
    private String staffs; // 스텝
    // private String peopleNm; // 스텝명
    // private String peopleNmEn; // 스텝명(영문)
    private String staffRoleNm; // 스텝역할명

    private String directorNm;     // 감독명
    private String openStartDt;    // 조회시작 개봉연도 (YYYY)
    private String openEndDt;      // 조회종료 개봉연도 (YYYY)
    private String prdtStartYear;  // 조회시작 제작연도 (YYYY)
    private String prdtEndYear;    // 조회종료 제작연도 (YYYY)
    private String repNationCd;     // 국적코드
    private String movieTypeCd;     // 영화유형코드
    private String nationAlt;       // 제작국가 (전체)
    private String genreAlt;        // 영화장르 (전체)
    private String repNationNm;     // 대표 제작국가명
    private String repGenreNm;      // 대표 장르명

}
